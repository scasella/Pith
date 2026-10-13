"""harness/oracle.py — what the contract requires for a driver program, computed by the verified core. FROZEN.

The decisions come from harness/oracle-py (the Python translation of spec/QuotaCore.dfy, reproduced on every judge).
What the core assumes and the library must establish itself is written here, from harness/LIBRARY.md, and is not
verified: the domain of whole numbers and keys (the translated core checks no preconditions), which error a malformed
call raises, that arguments are checked before the clock, that a `burst` is a sequence of acquires, and that dump/load
carries the whole state. `expected(program, runtime)` returns the results a conforming library's driver prints, in
the drivers' shapes, up to `comparable()` (which drops what this harness does not judge: messages, dump texts, the
error attributes that delivery/ judges).
"""
import math, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "oracle-py"))
import _dafny, module_, QuotaSpec, QuotaCore   # noqa: E402,F401  (module_ first: the translator's import order)

U31, U53 = 2 ** 31 - 1, 2 ** 53 - 1
KEY = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
CORE = QuotaCore.Core()


class Invalid(Exception):
    def __init__(self, argument): self.argument = argument


def whole(v, runtime, lo, hi):
    """A whole number as LIBRARY.md § Values defines it for the runtime (JSON 1.0 reaches Node.js as 1)."""
    if isinstance(v, bool): return False
    if isinstance(v, float) and runtime == "node" and math.isfinite(v) and v.is_integer(): v = int(v)
    return isinstance(v, int) and lo <= v <= hi


def need(ok, argument):
    if not ok: raise Invalid(argument)


def dkey(k): return _dafny.SeqWithoutIsStrInference(map(_dafny.CodePoint, k))


class Ref:
    """One limiter: a configuration and a State of the verified core."""
    def __init__(self, limit, window):
        self.c = QuotaSpec.Config_Config(int(limit), int(window)); self.s = QuotaSpec.State_State(0, _dafny.SeqWithoutIsStrInference([]))

    def acquire(self, key, now, cost):
        d, s2 = CORE.Acquire(self.c, self.s, dkey(key), int(cost), int(now))
        if d.is_Regressed: return {"error": "ClockRegression", "clock": int(self.s.clock)}
        self.s = s2
        if d.is_Granted: return {"ok": {"granted": True, "remaining": int(d.remaining), "retry_after": None}}
        return {"ok": {"granted": False, "remaining": int(d.remaining), "retry_after": int(d.retryAfter.value) if d.retryAfter.is_Some else None}}

    def peek(self, key, now):
        regressed, remaining, s2 = CORE.Peek(self.c, self.s, dkey(key), int(now))
        if regressed: return {"error": "ClockRegression", "clock": int(self.s.clock)}
        self.s = s2; return {"ok": int(remaining)}

    def copy(self):
        r = Ref.__new__(Ref); r.c, r.s = self.c, self.s; return r


def expected(program, runtime):
    lims, dumps, out = {}, {}, []
    for s in program["steps"]:
        op = s["op"]
        try:
            if op == "new":
                need(whole(s.get("limit"), runtime, 1, U31), "limit"); need(whole(s.get("window"), runtime, 1, U31), "window")
                lims[s["id"]] = Ref(s["limit"], s["window"]); r = {"ok": None}
            elif op in ("acquire", "peek", "burst"):
                need(isinstance(s.get("key"), str) and KEY.fullmatch(s["key"]) is not None, "key")
                if op != "peek" and "cost" in s: need(whole(s["cost"], runtime, 1, U31), "cost")
                need(whole(s.get("now"), runtime, 0, U53), "now")
                lim = lims[s["id"]]
                if op == "acquire": r = lim.acquire(s["key"], s["now"], s.get("cost", 1))
                elif op == "peek": r = lim.peek(s["key"], s["now"])
                else:
                    n = 0                     # a burst: threads * calls acquires at one instant, call j on key f"{key}{j % keys}"
                    keys = s.get("keys")
                    for kk in (range(keys) if keys else [None]):
                        key = f'{s["key"]}{kk}' if keys else s["key"]
                        calls = s["threads"] * (len(range(kk, s["calls"], keys)) if keys else s["calls"])
                        for _ in range(calls):
                            x = lim.acquire(key, s["now"], s["cost"])
                            if not x.get("ok", {}).get("granted"): break  # a denial changes nothing [Q2], so every later call on
                            n += 1                                        # this key at this instant is denied too (saves the retry search)
                    r = {"ok": {"granted": n, "errors": []}}
            elif op == "dump": dumps[s["id"]] = lims[s["id"]].copy(); r = {"ok": {"type": "str"}}
            elif op == "load":
                if "from" in s and not s.get("truncate"): lims[s["id"]] = dumps[s["from"]].copy(); r = {"ok": None}
                else: raise Invalid("text")
            elif op == "sleep": r = {"ok": None}
            else: raise ValueError(op)
        except Invalid as e:
            r = {"error": "InvalidArgument", "argument": e.argument}
        out.append(r)
    return out


def comparable(r):
    """The part of a result this harness judges: decisions, peeks, which error, and that dump returned text."""
    if "error" in r: return {"error": r["error"]}
    v = r["ok"]
    if isinstance(v, dict) and "type" in v: return {"ok": {"type": v["type"]}}
    if isinstance(v, dict) and "errors" in v: return {"ok": {"granted": v["granted"], "errors": v["errors"]}}
    if isinstance(v, dict):                       # a decision: exact types matter (True is not 1, None is not 0)
        return {"ok": {k: (type(x).__name__, x) for k, x in sorted(v.items())}}
    return {"ok": (type(v).__name__, v)}
