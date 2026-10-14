"""
harness/lifecycle.py — the approval service judged BLACK-BOX, through its HTTP API, as a separate process. FROZEN.
Separation of duties, revision-bound approvals, each document's quorum (chosen at creation, never changed),
publishing, idempotency, crash and restart, and concurrent approvals and edits. Nothing here imports candidate code.
"""
import itertools, pathlib, sys
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service

ROLES = {"alice": ["editor", "approver"], "bob": ["editor", "approver"], "carol": ["approver"], "dave": ["publisher"], "erin": ["approver"], "frank": ["approver"]}
RQ = itertools.count(1)


@pytest.fixture
def svc():
    s = Service(ROOT).start()
    for a, r in ROLES.items(): assert s.client.actor(a, r)[0] == 201
    try: yield s
    finally: s.stop()


def do(c, op, doc, actor, revision=None, rq=None, body="next"):
    rq = rq or next(RQ)
    code, r = (c.create(rq, doc, actor) if op == "create" else c.edit(rq, doc, actor, body) if op == "edit" else c.cmd(op, rq, doc, actor, revision))
    assert code == 200, (op, code, r)
    return r


def ok(r): return r["outcome"] == "OK"
def why(r): return r["outcome"] == "REFUSED" and r["reason"]


def test_actors_are_registered_with_roles(svc):
    """Contract: A2."""
    c = svc.client
    assert c.actor("alice", ["approver"])[0] == 409
    assert {a["id"]: sorted(a["roles"]) for a in c.actors()[1]["actors"]} == {a: sorted(r) for a, r in ROLES.items()}


def test_the_happy_path_needs_two_distinct_approvers_then_a_publisher(svc):
    """Contract: A3, A5."""
    c = svc.client
    assert ok(do(c, "create", "memo", "alice")) and ok(do(c, "submit", "memo", "alice", 1))
    r = do(c, "approve", "memo", "bob", 1); assert ok(r) and r["document"]["status"] == "in_review" and r["document"]["current_votes"] == ["bob"]
    assert why(do(c, "approve", "memo", "bob", 1)) == "ALREADY_APPROVED"
    r = do(c, "approve", "memo", "carol", 1); assert ok(r) and r["document"]["status"] == "approved"
    assert why(do(c, "publish", "memo", "carol", 1)) == "ROLE"
    r = do(c, "publish", "memo", "dave", 1); assert ok(r) and r["document"]["status"] == "published"
    assert why(do(c, "edit", "memo", "alice")) == "WRONG_STATE" and c.document("memo")[1]["revision"] == 1      # published is final


def test_separation_of_duties_is_per_revision(svc):
    """Contract: A1."""
    c = svc.client
    do(c, "create", "spec", "alice"); do(c, "submit", "spec", "alice", 1)
    assert why(do(c, "approve", "spec", "alice", 1)) == "SEPARATION_OF_DUTIES" and why(do(c, "reject", "spec", "alice", 1)) == "SEPARATION_OF_DUTIES"
    do(c, "edit", "spec", "bob"); assert c.document("spec")[1]["status"] == "draft"
    assert why(do(c, "submit", "spec", "alice", 2)) == "NOT_AUTHOR" and ok(do(c, "submit", "spec", "bob", 2))
    assert ok(do(c, "approve", "spec", "alice", 2))                                       # alice did not write revision 2
    assert why(do(c, "approve", "spec", "bob", 2)) == "SEPARATION_OF_DUTIES"
    d = c.document("spec")[1]; assert d["approvals"] == [{"revision": 2, "actor": "alice"}] and d["status"] == "in_review"


def test_approvals_are_bound_to_a_revision_and_stale_ones_never_count(svc):
    """Contract: A3."""
    c = svc.client
    do(c, "create", "plan", "alice"); do(c, "submit", "plan", "alice", 1); do(c, "approve", "plan", "bob", 1)
    do(c, "edit", "plan", "alice"); do(c, "submit", "plan", "alice", 2)
    assert why(do(c, "approve", "plan", "carol", 1)) == "STALE_REVISION"
    d = c.document("plan")[1]; assert d["status"] == "in_review" and d["current_votes"] == [] and {"revision": 1, "actor": "bob"} in d["approvals"]
    assert ok(do(c, "approve", "plan", "carol", 2)) and c.document("plan")[1]["status"] == "in_review"       # bob's revision-1 vote is history
    assert ok(do(c, "approve", "plan", "bob", 2)) and c.document("plan")[1]["status"] == "approved"
    do(c, "edit", "plan", "bob")                                                         # an edit after approval starts over
    d = c.document("plan")[1]; assert d["status"] == "draft" and d["revision"] == 3 and d["current_votes"] == []
    assert why(do(c, "publish", "plan", "dave", 2)) == "STALE_REVISION" and why(do(c, "publish", "plan", "dave", 3)) == "WRONG_STATE"


def test_rejection_and_roles(svc):
    """Contract: A2."""
    c = svc.client
    assert why(do(c, "create", "x", "carol")) == "ROLE" and c.document("x")[0] == 404
    assert why(do(c, "create", "y", "nobody")) == "ROLE"
    do(c, "create", "z", "bob"); assert why(do(c, "approve", "z", "carol", 1)) == "WRONG_STATE"
    do(c, "submit", "z", "bob", 1); assert why(do(c, "approve", "z", "dave", 1)) == "ROLE"
    assert ok(do(c, "reject", "z", "erin", 1)) and c.document("z")[1]["status"] == "rejected"
    assert why(do(c, "approve", "z", "carol", 1)) == "WRONG_STATE"
    assert ok(do(c, "edit", "z", "bob")) and c.document("z")[1]["status"] == "draft"
    assert c.cmd("approve", next(RQ), "nope", "carol", 1)[0] == 404


def test_replays_are_idempotent_and_conflicting_reuse_is_rejected(svc):
    """Contract: Idempotency."""
    c = svc.client
    do(c, "create", "doc", "alice", rq=101); do(c, "submit", "doc", "alice", 1, rq=102)
    a = do(c, "approve", "doc", "bob", 1, rq=103); n = len(c.events()[1])
    b = do(c, "approve", "doc", "bob", 1, rq=103)
    assert b["replayed"] is True and b["outcome"] == a["outcome"] and len(c.events()[1]) == n
    r = do(c, "approve", "doc", "alice", 1, rq=104); again = do(c, "approve", "doc", "alice", 1, rq=104)
    assert why(r) == "SEPARATION_OF_DUTIES" and again["replayed"] is True and why(again) == "SEPARATION_OF_DUTIES"
    assert c.cmd("approve", 103, "doc", "carol", 1)[0] == 409 and c.cmd("reject", 103, "doc", "bob", 1)[0] == 409
    assert c.document("doc")[1]["current_votes"] == ["bob"]


def test_crash_after_commit_then_restart_and_retry_replays(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client
    do(c, "create", "rfc", "alice", rq=201); do(c, "submit", "rfc", "alice", 1, rq=202); do(c, "approve", "rfc", "bob", 1, rq=203)
    svc.kill(); c = svc.start().client
    r = do(c, "approve", "rfc", "bob", 1, rq=203)
    assert r["replayed"] is True and ok(r) and c.document("rfc")[1]["current_votes"] == ["bob"]
    assert [e["type"] for e in c.events()[1] if e.get("request_id") == 203].count("op.committed") == 1
    assert ok(do(c, "approve", "rfc", "carol", 1)) and c.document("rfc")[1]["status"] == "approved"


def test_restart_preserves_documents_actors_and_history(svc):
    """Contract: Durability."""
    c = svc.client
    do(c, "create", "a1", "alice"); do(c, "submit", "a1", "alice", 1); do(c, "approve", "a1", "bob", 1); do(c, "edit", "a1", "bob", body="second")
    view, actors = c.document("a1")[1], c.actors()[1]
    c = svc.restart().client
    assert c.document("a1")[1] == view and c.actors()[1] == actors
    assert [x["body"] for x in view["revisions"]] == ["v1", "second"] and [x["author"] for x in view["revisions"]] == ["alice", "bob"]


def test_concurrent_approvals_reach_the_quorum_exactly_once(svc):
    """Contract: Atomicity, A3."""
    c = svc.client
    for k in range(6):
        doc = f"q{k}"; do(c, "create", doc, "alice"); do(c, "submit", doc, "alice", 1)
        with ThreadPoolExecutor(4) as ex: res = list(ex.map(lambda a: do(c, "approve", doc, a, 1), ["bob", "carol", "erin", "frank"]))
        d = c.document(doc)[1]
        assert [r["outcome"] for r in res].count("OK") == 2 and d["status"] == "approved" and len(d["current_votes"]) == 2, (res, d)
        assert sorted(r["reason"] for r in res if r["outcome"] == "REFUSED") == ["WRONG_STATE", "WRONG_STATE"]


def test_the_quorum_is_the_documents_chosen_at_creation(svc):
    """Contract: A3, A9."""
    c = svc.client
    code, r = c.create(next(RQ), "board", "alice", quorum=3); assert code == 200 and ok(r) and r["document"]["quorum"] == 3
    assert c.document("board")[1]["quorum"] == 3
    do(c, "submit", "board", "alice", 1)
    assert ok(do(c, "approve", "board", "bob", 1)) and ok(do(c, "approve", "board", "carol", 1))
    d = c.document("board")[1]; assert d["status"] == "in_review" and d["current_votes"] == ["bob", "carol"]          # two of three
    assert why(do(c, "publish", "board", "dave", 1)) == "WRONG_STATE"
    r = do(c, "approve", "board", "erin", 1); assert ok(r) and r["document"]["status"] == "approved" and r["document"]["quorum"] == 3
    assert why(do(c, "approve", "board", "frank", 1)) == "WRONG_STATE"
    assert ok(do(c, "publish", "board", "dave", 1)) and c.document("board")[1]["quorum"] == 3
    r = do(c, "create", "plain", "bob"); assert r["document"]["quorum"] == 2                                            # omitted: 2
    do(c, "submit", "plain", "bob", 1); do(c, "approve", "plain", "alice", 1)
    assert ok(do(c, "approve", "plain", "carol", 1)) and c.document("plain")[1]["status"] == "approved"


def test_the_quorum_never_changes_after_creation(svc):
    """Contract: A9, A3, Durability."""
    c = svc.client
    c.create(next(RQ), "charter", "alice", quorum=3); do(c, "submit", "charter", "alice", 1); do(c, "approve", "charter", "carol", 1)
    do(c, "edit", "charter", "bob"); do(c, "submit", "charter", "bob", 2)                     # an edit starts review over; the quorum stays
    assert ok(do(c, "approve", "charter", "alice", 2)) and ok(do(c, "approve", "charter", "carol", 2))
    d = c.document("charter")[1]; assert d["quorum"] == 3 and d["status"] == "in_review" and d["current_votes"] == ["alice", "carol"]
    c = svc.restart().client
    assert c.document("charter")[1]["quorum"] == 3
    assert ok(do(c, "approve", "charter", "erin", 2)) and c.document("charter")[1]["status"] == "approved"
    assert {"revision": 1, "actor": "carol"} in c.document("charter")[1]["approvals"]                                   # stale votes stay history
    for args in (("charter", "carol", 1), ("charter", "frank", 2)):                          # no command takes or changes a quorum
        assert c.cmd("approve", next(RQ), *args)[0] == 200
    assert c.document("charter")[1]["quorum"] == 3


def test_create_replays_and_the_quorum_is_part_of_the_command(svc):
    """Contract: Idempotency, A9."""
    c = svc.client
    a = c.create(401, "q-doc", "alice", quorum=4)[1]; b = c.create(401, "q-doc", "alice", quorum=4)[1]
    assert b["replayed"] is True and b["document"]["quorum"] == 4 and a["document"] == b["document"]
    assert c.create(401, "q-doc", "alice", quorum=3)[0] == 409 and c.create(401, "q-doc", "alice")[0] == 409
    r = c.create(402, "d-doc", "bob")[1]; again = c.create(402, "d-doc", "bob", quorum=2)[1]                          # omitting it is naming 2
    assert again["replayed"] is True and again["document"] == r["document"] and r["document"]["quorum"] == 2
    assert c.document("q-doc")[1]["quorum"] == 4


def test_concurrent_approvals_reach_a_larger_quorum_exactly_once(svc):
    """Contract: Atomicity, A3."""
    c = svc.client
    for k in range(4):
        doc = f"q3-{k}"; c.create(next(RQ), doc, "alice", quorum=3); do(c, "submit", doc, "alice", 1)
        with ThreadPoolExecutor(4) as ex: res = list(ex.map(lambda a: do(c, "approve", doc, a, 1), ["bob", "carol", "erin", "frank"]))
        d = c.document(doc)[1]
        assert [r["outcome"] for r in res].count("OK") == 3 and d["status"] == "approved" and len(d["current_votes"]) == 3, (res, d)
        assert [r["reason"] for r in res if r["outcome"] == "REFUSED"] == ["WRONG_STATE"]


def test_concurrent_edits_and_approvals_never_approve_a_superseded_revision(svc):
    """Contract: Atomicity, A3."""
    c = svc.client
    for k in range(8):
        doc = f"r{k}"; do(c, "create", doc, "alice"); do(c, "submit", doc, "alice", 1); do(c, "approve", doc, "carol", 1)
        jobs = [("approve", "bob"), ("edit", "alice"), ("approve", "erin")]
        with ThreadPoolExecutor(3) as ex: list(ex.map(lambda j: do(c, j[0], doc, j[1], 1), jobs))
        d = c.document(doc)[1]
        assert d["status"] != "approved" or (d["revision"] == 1 and len(d["current_votes"]) >= 2), d
        assert d["revision"] == 2 and d["status"] == "draft" and d["current_votes"] == []         # the edit always lands; it resets review


def test_every_command_commits_once(svc):
    """Contract: Atomicity."""
    c = svc.client
    for rq, (op, a, r) in enumerate([("create", "alice", None), ("submit", "alice", 1), ("approve", "alice", 1), ("approve", "bob", 1)], start=301):
        do(c, op, "ev", a, r, rq=rq)
    evs = c.events()[1]
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs) and len({e["seq"] for e in evs}) == len(evs)
    assert [e["request_id"] for e in evs if e["type"] == "op.committed" and e.get("request_id", 0) >= 301] == [301, 302, 303, 304]
