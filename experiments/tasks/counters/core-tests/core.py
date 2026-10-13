"""core.py — the trusted decision for the counters task (core-tests condition). decide(tally, bound) -> (outcome, new tally)."""


def decide(tally, bound):
    if not (isinstance(tally, int) and isinstance(bound, int) and 0 <= tally <= bound): raise ValueError("0 <= tally <= bound")
    return ("OK", tally + 1) if tally < bound else ("REFUSED", tally)
