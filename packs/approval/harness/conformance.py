"""
harness/conformance.py — the running service agrees with the reference model (= the TLA+ spec within its bounds,
harness/refines.py), command by command. FROZEN.

Hypothesis generates command sequences over six actors with overlapping roles, revisions near the current one
(so stale and future revisions are common), and repeated approvals. Each sequence runs against a fresh document on
the candidate's service and through harness/reference.py; every outcome, every refusal reason and every resulting
document view must be the same. A test, not a proof: it is how a candidate that writes the whole workflow itself
is held to the spec.
"""
import itertools, pathlib, sys
import pytest
from hypothesis import given, settings, strategies as st, HealthCheck
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service
from harness import reference as R

ROLES = {"alice": ("editor", "approver"), "bob": ("editor", "approver"), "carol": ("approver",), "dave": ("publisher",), "erin": ("approver",), "zed": ()}
N = itertools.count(1)
cmd = st.tuples(st.sampled_from(["edit", "submit", "submit", "approve", "approve", "approve", "reject", "publish"]), st.sampled_from(sorted(ROLES)), st.integers(-1, 1))


@pytest.fixture(scope="module")
def svc():
    s = Service(ROOT).start()
    for a, r in ROLES.items():
        if r or a == "zed": s.client.actor(a, list(r))
    try: yield s
    finally: s.stop()


def shape(v):
    return {"status": v["status"], "revision": v["revision"], "authors": [x["author"] for x in v["revisions"]],
            "approvals": v["approvals"], "current_votes": v["current_votes"]}


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.sampled_from(["alice", "bob", "carol"]), st.lists(cmd, min_size=1, max_size=20))
def test_service_agrees_with_the_reference(svc, creator, seq):
    c = svc.client; doc = f"c{next(N)}"; rq = lambda: 10_000_000 + next(N)
    code, r = c.create(rq(), doc, creator); why, d = R.create(creator, ROLES)
    assert code == 200 and (r["outcome"], r["reason"]) == (("OK", None) if why is None else ("REFUSED", why)), f"create by {creator}: service {r}"
    if why: return
    for op, actor, off in seq:
        rev = d.rev + off
        code, r = (c.edit(rq(), doc, actor) if op == "edit" else c.cmd(op, rq(), doc, actor, max(rev, 0)))
        why, d = R.step(d, op, actor, ROLES, None if op == "edit" else max(rev, 0))
        want = ("OK", None) if why is None else ("REFUSED", why)
        assert code == 200 and (r["outcome"], r["reason"]) == want, f"{op} by {actor} on revision {rev} of {R.view(d)}: service {r.get('outcome') if r else code}/{r.get('reason') if r else ''}, reference {want}"
        got = shape(c.document(doc)[1]); exp = R.view(d)
        assert got == exp, f"after {op} by {actor}: service {got}, reference {exp}"
