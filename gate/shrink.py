"""
gate/shrink.py — the shortest step sequence that still shows a failure. FROZEN. Domain-free.

Two reductions, both deterministic (the same steps and the same predicate give the same result):

  truncate(steps, i)        drop every step after the first diverging one (always sound for a sequential replay)
  ddmin(steps, fails)       delta debugging (Zeller and Hildebrandt, 2002): a 1-minimal subsequence for which
                            fails(subsequence) still holds; with keep_last the diverging step itself is always kept

A predicate here is offline and deterministic: a pack's oracle replaying steps through its verified core or reference
model (`oracle(cmd, steps)`: the pack's command reads {"steps": [...]} as JSON on stdin and prints {"outcomes": [...]},
one per step). Nothing live is re-run while shrinking, so a shrunk sequence reproduces the situation in the oracle;
whether a candidate fails on it too is known only by replaying it (gate/trace.py replay). Used by gate/packet.py and
gate/trace.py (docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 5, § 7).
"""
import json, subprocess


def truncate(steps, first_divergence):
    return list(steps[:first_divergence + 1])


def ddmin(steps, fails, keep_last=False, budget=4000):
    """(minimal steps, number of predicate calls). `fails(steps)` must hold for the input; the result is 1-minimal: no
    single step can be removed without fails() becoming false (within the call budget; past it, the best found)."""
    steps = list(steps); calls = [0]; cache = {}
    tail = steps[-1:] if keep_last and steps else []
    body = steps[:-1] if keep_last and steps else steps

    def test(idx):
        key = tuple(idx)
        if key not in cache:
            if calls[0] >= budget: return False
            calls[0] += 1; cache[key] = bool(fails([body[i] for i in idx] + tail))
        return cache[key]

    c = list(range(len(body)))
    if not test(c): raise ValueError("the predicate does not hold for the full sequence: nothing to shrink")
    n = 2
    while len(c) >= 2:
        size = len(c) // n; chunks = [c[i * size:(i + 1) * size] if i < n - 1 else c[i * size:] for i in range(n)]
        for ch in chunks:
            if test(ch): c, n = ch, 2; break
        else:
            for i in range(n):
                comp = [x for j, ch in enumerate(chunks) if j != i for x in ch]
                if test(comp): c, n = comp, max(n - 1, 2); break
            else:
                if n >= len(c): break
                n = min(n * 2, len(c))
    if len(c) == 1 and test([]): c = []
    return [body[i] for i in c] + tail, calls[0]


def oracle(cmd, steps, cwd=None, timeout=120):
    """Outcomes the pack's offline oracle gives for these steps (a list, one per step), or raise."""
    r = subprocess.run(cmd, shell=True, cwd=cwd, input=json.dumps({"steps": steps}), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(f"oracle failed ({r.returncode}): {(r.stderr or r.stdout)[-400:]}")
    return json.loads(r.stdout)["outcomes"]
