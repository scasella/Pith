"""harness/driver.py — runs one program against the candidate's Python library. FROZEN. Pack code that the harness
starts AS THE CANDIDATE (gate/sandbox.py:run_as_candidate_full); it is the only pack code that imports the candidate's
library, and it runs in the candidate's process, never the judge's.

    python3 -I harness/driver.py '<json program>'       prints one JSON line: {"results": [...]}

Steps (harness/LIBRARY.md § How the pack drives it): {"op": "new", "id", "limit", "window", "limits"?} | {"op": "acquire",
"id", "key", "now", "cost"?} | {"op": "peek", "id", "key", "now"} | {"op": "limit_for", "id", "key"} | {"op": "dump", "id"}
| {"op": "load", "id", "from" | "text", "truncate"?} | {"op": "burst", "id", "key", "now", "cost", "threads", "calls", "keys"?}
| {"op": "sleep", "ms"}. A missing "cost" or "limits" is not passed.

    python3 -I harness/driver.py --interleave '<json>'  prints one JSON line: {"interleave": {...}}   (v0.13.0)

The interleave mode explores the schedules of K threads calling acquire for the same key on a fresh limiter, with gate/interleave.py
(docs/rfc/0007 § 6): the threads run one at a time and switch at every lock, every sleep and every line of the candidate's lib/, so
a defect reachable within `bound` preemptions is found on every run. The program is {"limit", "window", "key", "now", "preload"?,
"threads"?, "bound"?}: `preload` units of the key are taken in turn first, so the threads race for the last `limit - preload`. The
controller is installed BEFORE the library is imported (it replaces threading.Lock and time.sleep for the code that follows).
"""
import json, pathlib, sys, threading, time        # everything the driver needs, imported before lib/ is on sys.path

ROOT = pathlib.Path(__file__).resolve().parent.parent
INTERLEAVE = sys.argv[1:2] == ["--interleave"]
if INTERLEAVE:                                    # v0.13.0: the controller goes in before the library is imported; it is loaded by path, so
    import importlib.util                         # that gate/ is not on sys.path where a candidate module could meet it
    _spec = importlib.util.spec_from_file_location("interleave", ROOT / "gate" / "interleave.py")
    IL = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(IL)
    IL.install(roots=[ROOT / "lib"])
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
            if op == "new":
                kw = {"limits": s["limits"]} if "limits" in s else {}
                lims[s["id"]] = L.Limiter(limit=s["limit"], window=s["window"], **kw); r = {"ok": None}
            elif op == "acquire":
                kw = {"now": s["now"]} if "cost" not in s else {"now": s["now"], "cost": s["cost"]}
                r = {"ok": decision(lims[s["id"]].acquire(s["key"], **kw))}
            elif op == "peek": r = {"ok": lims[s["id"]].peek(s["key"], now=s["now"])}
            elif op == "limit_for": r = {"ok": lims[s["id"]].limit_for(s["key"])}
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


def interleave(prog):
    """Every schedule, within the preemption bound, of `threads` calls to acquire(key) on a fresh limiter holding `limit - preload`
    units of the key: exactly that many (or all of them, if fewer) must be granted, and no call may fail."""
    limit, key, now, k = prog["limit"], prog["key"], prog["now"], prog.get("threads", 2)
    left = limit - prog.get("preload", 0)

    def setup():
        lim = L.Limiter(limit=limit, window=prog["window"])
        for _ in range(prog.get("preload", 0)): lim.acquire(key, now=now)
        return lim

    def call(lim): return decision(lim.acquire(key, now=now))

    def check(lim, results):
        bad = [r[1] for r in results if r[0] != "ok"]
        if bad: return f"a call failed: {bad[0]}"
        granted = sum(1 for r in results if r[1]["granted"])
        if granted != min(k, left): return f"{granted} of {k} calls granted for {left} unit(s) left"
        if lim.peek(key, now=now) != max(left - k, 0): return f"{granted} granted but {lim.peek(key, now=now)} left, not {max(left - k, 0)}"

    rep = IL.explore(setup, [call] * k, check, bound=prog.get("bound", 1))
    return {**{x: rep[x] for x in ("schedules", "bound", "complete")}, "violations": len(rep["violations"]), "first": rep["first"],
            "inconclusive": rep["inconclusive"][:3], "deadlocks": rep["deadlocks"][:3]}


if __name__ == "__main__":
    if INTERLEAVE: print(json.dumps({"interleave": interleave(json.loads(sys.argv[2]))}))
    else: main()
