"""harness/tracedata.py — the reviewed traces of spec/TraceData.dfy as data, for the harnesses. FROZEN.

spec/TraceData.dfy is the one place the reviewed traces are written. The Dafny checks run them against the verified
core and the known-wrong cores; harness/lifecycle.py runs them through the candidate's library with this parser.
"""
import pathlib, re

SRC = pathlib.Path(__file__).resolve().parent.parent / "spec" / "TraceData.dfy"
TRACE = re.compile(r'Trace\("(\w+)", Config\((\d+), (\d+), map\[([^\]]*)\]\), \[(.*?)\]\)', re.S)
OWN = re.compile(r'"([^"]+)" := (\d+)')
STEP = re.compile(r'Step\("([^"]+)", (\d+), (\d+), (G\((\d+)\)|D\((\d+), (\d+)\)|Never\((\d+)\)|Regressed)\)')


def traces():
    """[(name, limit, window, {key: own limit}, [(key, cost, now, expected driver result)])] in file order."""
    out = []
    for m in TRACE.finditer(SRC.read_text()):
        steps = []
        for s in STEP.finditer(m.group(5)):
            key, cost, now, d = s.group(1), int(s.group(2)), int(s.group(3)), s.group(4)
            if d.startswith("G("): want = {"ok": {"granted": True, "remaining": int(s.group(5)), "retry_after": None}}
            elif d.startswith("D("): want = {"ok": {"granted": False, "remaining": int(s.group(6)), "retry_after": int(s.group(7))}}
            elif d.startswith("Never("): want = {"ok": {"granted": False, "remaining": int(s.group(8)), "retry_after": None}}
            else: want = {"error": "ClockRegression"}
            steps.append((key, cost, now, want))
        own = {k: int(v) for k, v in OWN.findall(m.group(4))}
        out.append((m.group(1), int(m.group(2)), int(m.group(3)), own, steps))
    return out


def program(limit, window, own, steps):
    """The trace as a driver program; `limits` is passed only when the trace names keys with a limit of their own."""
    return [{"op": "new", "id": "T", "limit": limit, "window": window, **({"limits": own} if own else {})}] + \
           [{"op": "acquire", "id": "T", "key": k, "cost": c, "now": n} for k, c, n, _ in steps]
