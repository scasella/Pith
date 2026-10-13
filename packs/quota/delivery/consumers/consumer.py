"""delivery/consumers/consumer.py — a programmer's use of the candidate's Python library. FROZEN.
Run by delivery/delivery_adapter.py AS THE CANDIDATE (gate/sandbox.py:run_as_candidate_full), never imported by the
judge. One subcommand per obligation of delivery/CONSUMER-CONTRACT.md; each prints one JSON line (except `silent`).

    python3 -I delivery/consumers/consumer.py silent | quickstart | errors | values | growth
    python3 -I delivery/consumers/consumer.py backoff '<json>' | persist-a '<json>' | persist-b '<dump text>' '<json>'
"""
import json, pathlib, sys

sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent.parent / "lib"))
cmd = sys.argv[1]
from limiter import Limiter, LimiterError, InvalidArgument, ClockRegression   # noqa: E402


def dec(d): return [d.granted, d.remaining, d.retry_after]


def calls(lim, steps):
    out = []
    for key, now, cost in steps:
        try: out.append(dec(lim.acquire(key, now=now, cost=cost)))
        except LimiterError as e: out.append(type(e).__name__)
    return out


if cmd == "silent":
    pass
elif cmd == "quickstart":                                      # harness/LIBRARY.md § The API, as written
    lim = Limiter(limit=3, window=60)
    d = lim.acquire("alice", now=10)
    r = [dec(d), dec(lim.acquire("alice", now=10, cost=2)), dec(lim.acquire("alice", now=11)), lim.peek("alice", now=11)]
    text = lim.dump()
    lim2 = Limiter.load(text)
    r += [lim2.peek("alice", now=70), dec(lim2.acquire("alice", now=70, cost=3)), lim.peek("alice", now=69)]
    print(json.dumps(r))
elif cmd == "backoff":
    w = json.loads(sys.argv[2]); lim = Limiter(limit=w["limit"], window=w["window"]); t = 0; out = []
    for key, arrival, cost in w["arrivals"]:
        t = max(t, arrival); attempts = 0
        while True:
            d = lim.acquire(key, now=t, cost=cost); attempts += 1
            if d.granted: out.append([t, attempts]); break
            if d.retry_after is None: out.append([None, attempts]); break
            if attempts > 3: out.append(["gave up", attempts]); break
            t += d.retry_after                                 # wait exactly what the limiter said
    print(json.dumps(out))
elif cmd == "errors":
    lim = Limiter(limit=2, window=10); lim.acquire("k", now=50); out = {}
    tries = {"limit": lambda: Limiter(limit=0, window=10), "window": lambda: Limiter(limit=1, window=-3),
             "key": lambda: lim.acquire("no spaces", now=60), "cost": lambda: lim.acquire("k", now=60, cost=0),
             "now": lambda: lim.acquire("k", now=-1), "text": lambda: Limiter.load("not a dump"), "regression": lambda: lim.acquire("k", now=49)}
    for name, f in tries.items():
        try: f(); out[name] = {"raised": None}
        except LimiterError as e:
            out[name] = {"raised": type(e).__name__, "base": True, "value_error": isinstance(e, ValueError),
                         "invalid": isinstance(e, InvalidArgument), "regression": isinstance(e, ClockRegression),
                         "argument": getattr(e, "argument", None), "clock": getattr(e, "clock", None), "message": bool(str(e).strip())}
        except Exception as e:
            out[name] = {"raised": type(e).__name__, "base": False}
    print(json.dumps(out))
elif cmd == "persist-a":
    w = json.loads(sys.argv[2]); lim = Limiter(limit=w["limit"], window=w["window"])
    r = calls(lim, w["before"]); print(json.dumps({"decisions": r, "dump": lim.dump()}))
elif cmd == "persist-b":
    w = json.loads(sys.argv[3]); lim = Limiter.load(sys.argv[2])
    print(json.dumps({"decisions": calls(lim, w["after"])}))
elif cmd == "values":
    lim = Limiter(limit=2, window=10)
    a = lim.acquire("k", now=0); before = dec(a)
    b = lim.acquire("k", now=0, cost=2); lim.acquire("k", now=3); lim.acquire("j", now=4)
    print(json.dumps({"before": before, "after": dec(a), "second": dec(b)}))
elif cmd == "growth":
    lim = Limiter(limit=10, window=10); granted = 0
    for i in range(20000): granted += lim.acquire("k", now=i).granted
    print(json.dumps({"granted": granted, "dump_length": len(lim.dump())}))
