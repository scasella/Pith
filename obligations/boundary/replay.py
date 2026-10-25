"""
obligations/boundary/replay.py — a harvested trace (pith.trace/v1) replayed against the candidate's service. FROZEN.

    PITH_TRACE=trace.yaml  pytest obligations/boundary/replay.py              (`traces.replay` in pack.yaml; gate/trace.py replay)

The candidate's service is started the way the judge starts it (obligations/service/supervisor.py: a separate process, scrubbed
environment, a database the harness owns), every step of the trace is sent through the frozen client and the answer is compared with
the step's `expected`, the answer the contract requires (the offline oracle's, obligations/boundary/oracle.py). A step passes when
every field the oracle produces is in the answer with the same value; a refusal ({status: N}) passes on the same status, where a
conflict (409) may also be a 400, as in the lifecycle harness. The test fails at the first step the service answers differently, naming it.

A trace shrunk against the oracle only (gate/trace.py harvest) is a claim about the oracle: this replay shows whether the candidate
fails it too. A candidate that passes did not reproduce the divergence the trace was harvested from (a fix, or a cause the shrunk
steps do not contain); a candidate that fails reproduced it.
"""
import json, os, pathlib, sys
import pytest, yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service


def load_trace():
    path = os.environ.get("PITH_TRACE")
    if not path: pytest.fail("PITH_TRACE names no trace: run this through `python3 gate/cli.py trace replay TRACE --candidate APP`")
    doc = yaml.safe_load(pathlib.Path(path).read_text())
    if not isinstance(doc, dict) or doc.get("format") != "pith.trace/v1" or not doc.get("steps"): pytest.fail(f"{path} is not a pith.trace/v1 trace with steps")
    return doc


def answer(client, step):
    """(status, body) of one step through the frozen client."""
    a, args = step["action"], step["args"]
    if a == "create_account": return client.create(args["account"], args["limit"])
    if a == "authorize": return client.authorize(args["account"], args["request"], args["amount"])
    if a == "release": return client.release(args["account"], args["request"])
    if a == "capture": return client.capture(args["account"], args["request"])
    pytest.fail(f"step {step.get('step')}: unknown action {a!r}")


def matches(expected, code, body):
    """Does the service's answer have every field of the answer the contract requires?"""
    if "status" in expected:
        want = expected["status"]
        return code == want or (want == 409 and code == 400)                      # a conflict: the lifecycle harness accepts either
    return code in (200, 201) and isinstance(body, dict) and all(k in body and body[k] == v and type(body[k]) is type(v) for k, v in expected.items())


@pytest.fixture
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()


def test_the_candidate_answers_every_step_as_the_trace_expects(svc):
    trace = load_trace()
    for step in trace["steps"]:
        code, body = answer(svc.client, step)
        got = body if code in (200, 201) and isinstance(body, dict) else {"status": code}
        if not matches(step["expected"], code, body):
            pytest.fail(f"step {step['step']} of {len(trace['steps'])} ({step['action']} {json.dumps(step['args'], sort_keys=True)}): "
                        f"the service answered {json.dumps(got, sort_keys=True)}, the contract requires {json.dumps(step['expected'], sort_keys=True)} "
                        f"(records {trace.get('records')}, alert {trace.get('alert')})", pytrace=False)
