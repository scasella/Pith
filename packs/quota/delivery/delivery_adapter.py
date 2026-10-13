"""
delivery/delivery_adapter.py — pith.quota's delivery adapter. FROZEN.

Called by the evaluator (kind `adapter`): run(ctx) -> {status: passed | failed, problems, claim, detail}. Delivery here
means what a programmer using the candidate's library gets (delivery/CONSUMER-CONTRACT.md): the frozen consumer
programs in delivery/consumers/ are run as the candidate's user (gate/sandbox.py:run_as_candidate_full); this module
only reads their output. Expected decisions come from the verified core (harness/oracle.py). No browser and no
service are involved, so this pack adds no release condition; it asks for no human evaluation.
"""
import json, pathlib, sys
import yaml

CONSUMER = {"python": [sys.executable, "-I", "delivery/consumers/consumer.py"], "node": ["node", "delivery/consumers/consumer.mjs"]}

BACKOFF = {"limit": 4, "window": 20, "arrivals": [["api", 0, 1]] * 7 + [["api", 25, 2]] * 3 + [["api", 30, 5], ["api", 31, 4], ["web", 31, 3], ["api", 90, 1]]}
PERSIST = {"limit": 3, "window": 10, "before": [["a", 0, 1], ["a", 2, 2], ["b", 3, 3], ["a", 4, 1]],
           "after": [["a", 3, 1], ["a", 9, 1], ["a", 10, 1], ["a", 12, 1], ["b", 12, 1], ["b", 13, 1], ["a", 12, 3]]}


def run(ctx):
    root = pathlib.Path(ctx.root); sys.path.insert(0, str(root))
    from gate import sandbox as SB
    from harness import oracle as O, run as R
    D = yaml.safe_load((root / "delivery/delivery.yaml").read_text())
    rt = R.runtime(root); runs = [0]; results = {}

    def consumer(*args):
        runs[0] += 1
        return SB.run_as_candidate_full(CONSUMER[rt] + list(args), cwd=root, timeout=60, limits=R.LIMITS[rt])

    def record(ob, ok, evidence):
        x = results.setdefault(ob, {"ok": True, "evidence": []}); x["ok"] &= bool(ok); x["evidence"].append(evidence)

    def json_of(code, out, err):
        if code != 0: raise AssertionError(f"consumer exited {code}: {(err or out)[-300:]}")
        return json.loads(out.strip().splitlines()[-1])

    def oracle_decisions(limit, window, steps):
        ref = O.Ref(limit, window); out = []
        for key, now, cost in steps:
            r = ref.acquire(key, now, cost)
            out.append(r["error"] if "error" in r else [r["ok"]["granted"], r["ok"]["remaining"], r["ok"]["retry_after"]])
        return out

    def attempt(ob, f):
        try: f()
        except Exception as e: record(ob, False, f"{type(e).__name__}: {e}")

    # LI1 a silent import
    def li1():
        code, out, err = consumer("silent")
        record("LI1", code == 0 and out == "" and err == "", f"import: exit {code}, stdout {out[:120]!r}, stderr {err[:200]!r}")
    attempt("LI1", li1)

    # LW1 the documented examples
    def lw1():
        got = json_of(*consumer("quickstart"))
        want = [[True, 2, None], [True, 0, None], [False, 0, 59], 0, 3, [True, 0, None], 0]   # harness/LIBRARY.md § The API, worked by hand
        record("LW1", got == want, f"quickstart gave {got}; the contract gives {want}")
    attempt("LW1", lw1)

    # LW2 a backoff client
    def lw2():
        got = json_of(*consumer("backoff", json.dumps(BACKOFF)))
        ref = O.Ref(BACKOFF["limit"], BACKOFF["window"]); t = 0; want = []
        for key, arrival, cost in BACKOFF["arrivals"]:
            t = max(t, arrival); attempts = 0
            while True:
                r = ref.acquire(key, t, cost)["ok"]; attempts += 1
                if r["granted"]: want.append([t, attempts]); break
                if r["retry_after"] is None: want.append([None, attempts]); break
                t += r["retry_after"]
        record("LW2", got == want and all(a <= 2 for _, a in got), f"backoff schedule [granted at, attempts] {got}; the verified core gives {want}")
    attempt("LW2", lw2)

    # LW3 errors a caller can handle
    def lw3():
        got = json_of(*consumer("errors")); bad = []
        for arg in ("limit", "window", "key", "cost", "now", "text"):
            g = got.get(arg, {})
            if not (g.get("base") and g.get("invalid") and g.get("value_error") and g.get("argument") == arg and g.get("message")):
                bad.append(f"{arg}: {g}")
        g = got.get("regression", {})
        if not (g.get("base") and g.get("regression") and not g.get("invalid") and g.get("clock") == 50 and g.get("message")): bad.append(f"regression: {g}")
        record("LW3", not bad, "every error handleable as LimiterError with its attributes" if not bad else "; ".join(bad)[:600])
    attempt("LW3", lw3)

    # LW4 state handed between processes
    def lw4():
        a = json_of(*consumer("persist-a", json.dumps(PERSIST)))
        b = json_of(*consumer("persist-b", a["dump"], json.dumps(PERSIST)))
        want = oracle_decisions(PERSIST["limit"], PERSIST["window"], PERSIST["before"] + PERSIST["after"])
        got = a["decisions"] + b["decisions"]
        record("LW4", got == want, f"decisions before and after the hand-over {got}; the verified core gives {want}")
    attempt("LW4", lw4)

    # LI2 decisions are values
    def li2():
        got = json_of(*consumer("values"))
        record("LI2", got["before"] == got["after"] == [True, 1, None] and got["second"] == [False, 1, 10],
               f"first decision {got['before']} -> {got['after']} after later calls; second {got['second']}")
    attempt("LI2", li2)

    # LI3 memory follows the window
    def li3():
        got = json_of(*consumer("growth"))
        record("LI3", got["granted"] == 20000 and got["dump_length"] < 2000, f"{got['granted']} of 20000 granted; dump() is {got['dump_length']} characters (must be under 2000)")
    attempt("LI3", li3)

    problems = [f"{w['id']} ({w['name']}) not demonstrated: {(results.get(w['id']) or {'evidence': ['not run']})['evidence'][0][:300]}"
                for w in D["required_workflows"] + D["required_interactions"] if not results.get(w["id"], {}).get("ok")]
    return {"status": "passed" if not problems else "failed", "problems": problems,
            "claim": f"consumer workflows {[w['id'] for w in D['required_workflows']]} and interaction obligations "
                     f"{[i['id'] for i in D['required_interactions']]} through frozen consumer programs ({runs[0]} runs as the candidate's user)",
            "detail": {"workflows": results, "problems": problems}}
