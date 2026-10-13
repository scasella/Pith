"""harness/driver.py — runs one program against the candidate's Python library. FROZEN. Pack code that the harness
starts AS THE CANDIDATE (gate/sandbox.py:run_as_candidate_full); it is the only pack code that imports the candidate's
library, and it runs in the candidate's process, never the judge's.

    python3 -I harness/driver.py '<json program>'       prints one JSON line: {"results": [...]}

Steps (harness/LIBRARY.md § How the pack drives it): {"op": "new", "id", "limit", "window"} | {"op": "acquire", "id",
"key", "now", "cost"?} | {"op": "peek", "id", "key", "now"} | {"op": "dump", "id"} | {"op": "load", "id", "from" | "text", "truncate"?}
| {"op": "burst", "id", "key", "now", "cost", "threads", "calls", "keys"?} | {"op": "sleep", "ms"}. A missing "cost" is not passed.
"""
import json, pathlib, sys, threading, time        # everything the driver needs, imported before lib/ is on sys.path

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "lib"))                # appended: a candidate module cannot shadow the standard library
import limiter as L                               # noqa: E402  (the candidate's library)


def err(e):
    for name in ("ClockRegression", "InvalidArgument"):
        if isinstance(e, getattr(L, name, ())): break
    else: name = "other"
    out = {"error": name, "type": type(e).__name__, "message": str(e)[:200],
           "is_base": isinstance(e, getattr(L, "LimiterError", ()))}
    for a in ("argument", "clock"):
        if hasattr(e, a): out[a] = getattr(e, a)
    return out


def decision(d):
    return {"granted": d.granted, "remaining": d.remaining, "retry_after": d.retry_after}


def main():
    prog = json.loads(sys.argv[1]); lims, dumps, results = {}, {}, []
    sys.setswitchinterval(1e-6)                    # make thread interleavings frequent (burst)
    for s in prog["steps"]:
        try:
            op = s["op"]
            if op == "new": lims[s["id"]] = L.Limiter(limit=s["limit"], window=s["window"]); r = {"ok": None}
            elif op == "acquire":
                kw = {"now": s["now"]} if "cost" not in s else {"now": s["now"], "cost": s["cost"]}
                r = {"ok": decision(lims[s["id"]].acquire(s["key"], **kw))}
            elif op == "peek": r = {"ok": lims[s["id"]].peek(s["key"], now=s["now"])}
            elif op == "dump":
                t = lims[s["id"]].dump(); dumps[s["id"]] = t; r = {"ok": {"type": type(t).__name__, "text": t if isinstance(t, str) else None}}
            elif op == "load":
                t = dumps[s["from"]] if "from" in s else s["text"]
                if s.get("truncate") and isinstance(t, str): t = t[: len(t) // 2]
                lims[s["id"]] = L.Limiter.load(t); r = {"ok": None}
            elif op == "burst":
                lim, granted, lock, errors = lims[s["id"]], [0], threading.Lock(), []
                def worker():
                    for j in range(s["calls"]):
                        try:
                            k = f'{s["key"]}{j % s["keys"]}' if s.get("keys") else s["key"]       # threads contend on the same key at once
                            if lim.acquire(k, now=s["now"], cost=s["cost"]).granted:
                                with lock: granted[0] += 1
                        except Exception as e: errors.append(repr(e))
                ts = [threading.Thread(target=worker) for _ in range(s["threads"])]
                for t in ts: t.start()
                for t in ts: t.join()
                r = {"ok": {"granted": granted[0], "errors": errors[:3]}}
            elif op == "sleep": time.sleep(s["ms"] / 1000); r = {"ok": None}
            else: r = {"error": "driver", "message": f"unknown op {op}"}
        except Exception as e:
            r = err(e)
        try: json.dumps(r)
        except (TypeError, ValueError): r = {"error": "driver", "message": f"result is not plain data: {r!r}"[:200]}
        results.append(r)
    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
