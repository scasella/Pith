"""
harness/conformance.py — the candidate's library agrees with the verified core, call by call. FROZEN.

Hypothesis generates programs: one limiter (small limit and window, so expiries, exact boundaries and retry hints are
common; usually one or two of its three keys with a limit of their own, above or below the default), calls by those
keys at mostly non-decreasing instants with occasional regressions, costs up to the key's limit + 1, peeks,
limit_for, and dump/load round trips after which the program continues on the loaded limiter. Each program runs in a fresh
driver process as the candidate and through harness/oracle.py (the translated spec/QuotaCore.dfy); every decision,
remaining count, retry hint and error must be the same. A test, not a proof.
"""
import pathlib, sys
from hypothesis import given, settings, strategies as st, HealthCheck
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import run as R, oracle as O

RT = R.runtime(ROOT)


@st.composite
def programs(draw):
    limit, window = draw(st.integers(1, 6)), draw(st.integers(1, 15))
    own = draw(st.dictionaries(st.sampled_from(["a", "b", "c"]), st.integers(1, 8), max_size=2))
    new = {"op": "new", "id": "L0", "limit": limit, "window": window}
    if own or draw(st.booleans()): new["limits"] = own
    steps, now, cur, n = [new], 0, "L0", 0
    for _ in range(draw(st.integers(1, 40))):
        kind = draw(st.sampled_from(["acquire"] * 6 + ["peek", "regress", "reload", "limit_for"]))
        if kind == "regress" and now > 0:
            steps.append({"op": "acquire", "id": cur, "key": "a", "now": draw(st.integers(0, now - 1)), "cost": 1}); continue
        if kind == "reload":
            n += 1; steps += [{"op": "dump", "id": cur}, {"op": "load", "id": f"L{n}", "from": cur}]; cur = f"L{n}"; continue
        now += draw(st.sampled_from([0, 0, 1, 1, 2, 3, window - 1, window, window + 1]))
        key = draw(st.sampled_from(["a", "a", "b", "c"]))
        if kind == "peek": steps.append({"op": "peek", "id": cur, "key": key, "now": now})
        elif kind == "limit_for": steps.append({"op": "limit_for", "id": cur, "key": key})
        else: steps.append({"op": "acquire", "id": cur, "key": key, "now": now, "cost": draw(st.integers(1, own.get(key, limit) + 1))})
    return steps


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(programs())
def test_library_agrees_with_the_verified_core(steps):
    got, want = R.run(steps, ROOT), O.expected({"steps": steps}, RT)
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {steps[i]}: library gave {g}, the verified core gives {w}"
