"""
migrations/verify.py — the approval-workflow/v2 service judged BLACK-BOX on state migrated from version 1. FROZEN.
gate/migrate.py runs it in the new release's workspace with PITH_MIGRATION_STATE (the migrated state directory) and
PITH_MIGRATION_OBSERVED (what migrations/populate.py saw the old service acknowledge). Each test starts the new
service (harness/SERVICE.md) on its own copy of the migrated state, so the tests are independent.
"""
import copy, json, os, pathlib, shutil, sys, tempfile
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service

STATE = pathlib.Path(os.environ["PITH_MIGRATION_STATE"]); OBS = json.loads(pathlib.Path(os.environ["PITH_MIGRATION_OBSERVED"]).read_text())


@pytest.fixture
def svc():
    d = pathlib.Path(tempfile.mkdtemp(prefix="migrated-")) / "state"; shutil.copytree(STATE, d)
    s = Service(ROOT, state=d).start()
    try: yield s
    finally: s.stop()


def send(c, rq, cmd):
    """The command exactly as a version 1 client sent it (no quorum)."""
    if cmd["op"] == "create": return c._req("POST", "/documents", {"request_id": rq, "id": cmd["doc"], "actor": cmd["actor"], "title": cmd["title"], "body": cmd["body"]})
    if cmd["op"] == "edit": return c.edit(rq, cmd["doc"], cmd["actor"], cmd["body"])
    return c.cmd(cmd["op"], rq, cmd["doc"], cmd["actor"], cmd["revision"])


def v2(doc):
    """A version 1 document as version 2 shows it: the same document, with quorum 2."""
    return None if doc is None else dict(doc, quorum=2)


def test_every_recorded_result_is_kept_and_replayed(svc):
    """Contract: MIG1, Idempotency."""
    c = svc.client
    for rq, cmd in OBS["commands"].items():
        code, got = send(c, int(rq), cmd); want = OBS["results"][rq]
        assert code == 200, (rq, cmd, code, got)
        assert got == dict(want, document=v2(want["document"]), replayed=True), (rq, cmd, want, got)


def test_an_old_approval_retried_is_replayed_not_refused(svc):
    """Contract: MIG1, Idempotency, A3."""
    c = svc.client
    rq = next(r for r, cmd in OBS["commands"].items() if cmd["op"] == "approve" and OBS["results"][r]["outcome"] == "OK")
    got = send(c, int(rq), OBS["commands"][rq])[1]
    assert got["outcome"] == "OK" and got["reason"] is None and got["replayed"] is True, got          # not ALREADY_APPROVED
    other = dict(OBS["commands"][rq], actor="erin" if OBS["commands"][rq]["actor"] != "erin" else "carol")
    assert send(c, int(rq), other)[0] == 409                                                            # an old request id reused for something else


def test_documents_actors_and_history_are_kept(svc):
    """Contract: MIG1, A3, A7."""
    c = svc.client
    for doc, view in OBS["documents"].items():
        if doc == "d-flight": continue                                                                  # test_in_flight_command_is_decided_at_most_once
        assert c.document(doc)[1] == v2(view), (doc, view, c.document(doc)[1])
    stale = c.document("d-stale")[1]
    assert {"revision": 1, "actor": "bob"} in stale["approvals"] and {"revision": 1, "actor": "carol"} in stale["approvals"], stale   # stale approvals are history
    assert c.actors()[1] == OBS["actors"]
    assert c.events()[1][:len(OBS["events"])] == OBS["events"]


def test_version_1_documents_keep_their_meaning(svc):
    """Contract: MIG1, A3, A5, A6."""
    c = svc.client
    r = c.cmd("approve", 5001, "d-review", "erin", 1)[1]                                                 # one approval more reaches quorum 2
    assert r["outcome"] == "OK" and r["document"]["status"] == "approved" and r["document"]["quorum"] == 2, r
    r = c.cmd("approve", 5002, "d-stale", "carol", 2)[1]                                                 # carol's revision-1 approval never counted for 2
    assert r["outcome"] == "OK" and r["document"]["status"] == "approved" and r["document"]["current_votes"] == ["carol", "erin"], r
    assert c.cmd("publish", 5003, "d-approved", "dave", 1)[1]["outcome"] == "OK"
    assert c.edit(5004, "d-published", "alice")[1]["reason"] == "WRONG_STATE" and c.cmd("submit", 5005, "d-rejected", "bob", 1)[1]["reason"] == "WRONG_STATE"
    assert c.cmd("submit", 5006, "d-draft", "alice", 1)[1]["outcome"] == "OK"


def test_in_flight_command_is_decided_at_most_once(svc):
    """Contract: MIG1, Idempotency, A3."""
    c = svc.client
    for f in OBS["in_flight"]:
        seen = OBS["documents"][f["cmd"]["doc"]]                                                       # as the restarted version 1 showed it
        assert c.document(f["cmd"]["doc"])[1] == v2(seen)
        recorded = f["cmd"]["actor"] in seen["current_votes"]                                           # version 1 decided it before it died
        first = send(c, f["rq"], f["cmd"])[1]; again = send(c, f["rq"], f["cmd"])[1]
        assert again == dict(first, replayed=True), (first, again)
        assert first["replayed"] is recorded and first["outcome"] == "OK", (recorded, first)            # replayed if recorded, decided once if not
        d = c.document(f["cmd"]["doc"])[1]
        assert d["current_votes"].count(f["cmd"]["actor"]) == 1 and d["status"] == "approved" and d["quorum"] == 2, d


def test_new_documents_choose_their_quorum_beside_old_ones(svc):
    """Contract: MIG1, A3, A9."""
    c = svc.client
    assert c.create(6001, "d-board", "bob", quorum=3)[1]["document"]["quorum"] == 3
    c.cmd("submit", 6002, "d-board", "bob", 1); c.cmd("approve", 6003, "d-board", "alice", 1); c.cmd("approve", 6004, "d-board", "carol", 1)
    assert c.document("d-board")[1]["status"] == "in_review"
    assert c.cmd("approve", 6005, "d-board", "erin", 1)[1]["document"]["status"] == "approved"
    assert all(c.document(d)[1]["quorum"] == 2 for d in OBS["documents"])
    old = copy.deepcopy(c.document("d-review")[1]); c.create(6006, "d-two", "alice")
    assert c.document("d-two")[1]["quorum"] == 2 and c.document("d-review")[1] == old
