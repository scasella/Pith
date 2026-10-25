"""obligations/service/trace.py — a harness's calls recorded as steps in the oracle's vocabulary. FROZEN.

A test that wraps the frozen client in a Trace keeps asserting exactly what it asserted; only its assertion messages
change. When the assertion that detects a defect fails, its message is one `pith-counterexample:` line (gate/packet.py
cx_line) carrying every call made so far as a step {step, action, args, observed}, the answer the contract requires at the
failing step and the contract records it bears on. The task packet reads the line and, because the steps are in the
vocabulary of obligations/boundary/oracle.py (`traces.oracle` in pack.yaml), shrinks them offline to the fewest calls that
still expect that answer (gate/shrink.py). The line holds domain words only: what was asked and what the service said.

    c = Trace(svc.client); c.create(1, 100); c.authorize(1, 1, 30)           # every other client method passes through
    want = {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True}
    assert c.authorize(1, 1, 30)[1] == want, c.cx(want, ["Idempotency"])
"""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from gate.packet import cx_line


class Trace:
    def __init__(self, client): self.c, self.steps = client, []
    def on(self, client): self.c = client; return self                 # after a restart: the same trace, the new client
    def __getattr__(self, name):                                       # reads (account, events, ...) are not steps
        if name in ("c", "steps"): raise AttributeError(name)
        return getattr(self.c, name)

    def _do(self, action, args, call):
        code, body = call
        # a refusal is its status alone: the oracle's outcome for a refusal, and nothing the candidate wrote in the body
        self.steps.append({"step": len(self.steps) + 1, "action": action, "args": args, "observed": body if code in (200, 201) and isinstance(body, dict) else {"status": code}})
        return code, body

    def create(self, a, limit): return self._do("create_account", {"account": a, "limit": limit}, self.c.create(a, limit))
    def authorize(self, a, r, amount): return self._do("authorize", {"account": a, "request": r, "amount": amount}, self.c.authorize(a, r, amount))
    def release(self, a, r): return self._do("release", {"account": a, "request": r}, self.c.release(a, r))
    def capture(self, a, r): return self._do("capture", {"account": a, "request": r}, self.c.capture(a, r))

    def cx(self, expected, violated):
        """The message of the assertion that detects the defect: the calls so far, the last one being where the service and the
        contract part, with the answer the contract requires there."""
        last = self.steps[-1]; last["expected"] = expected
        return cx_line(self.steps, expected=expected, observed=last["observed"], violated=violated, diverged_at=len(self.steps) - 1,
                       replayable=True, source="black-box harness")
