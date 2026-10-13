"""
harness/conformance.py — the candidate's library agrees with the verified core, call by call. FROZEN.

Hypothesis generates programs: one limiter (small limit and window, so expiries, exact boundaries and retry hints are
common), calls by three keys at mostly non-decreasing instants with occasional regressions, costs up to limit + 1,
peeks, and dump/load round trips after which the program continues on the loaded limiter. Each program runs in a fresh
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
    steps, now, cur, n = [{"op": "new", "id": "L0", "limit": limit, "window": window}], 0, "L0", 0
    for _ in range(draw(st.integers(1, 40))):
        kind = draw(st.sampled_from(["acquire"] * 6 + ["peek", "regress", "reload"]))
        if kind == "regress" and now > 0:
            steps.append({"op": "acquire", "id": cur, "key": "a", "now": draw(st.integers(0, now - 1)), "cost": 1}); continue
        if kind == "reload":
            n += 1; steps += [{"op": "dump", "id": cur}, {"op": "load", "id": f"L{n}", "from": cur}]; cur = f"L{n}"; continue
        now += draw(st.sampled_from([0, 0, 1, 1, 2, 3, window - 1, window, window + 1]))
        key = draw(st.sampled_from(["a", "a", "b", "c"]))
        if kind == "peek": steps.append({"op": "peek", "id": cur, "key": key, "now": now})
        else: steps.append({"op": "acquire", "id": cur, "key": key, "now": now, "cost": draw(st.integers(1, limit + 1))})
    return steps


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(programs())
def test_library_agrees_with_the_verified_core(steps):
    got, want = R.run(steps, ROOT), O.expected({"steps": steps}, RT)
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {steps[i]}: library gave {g}, the verified core gives {w}"
