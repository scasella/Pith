"""
migrations/verify.py — the authorization-and-posting/v3 service judged BLACK-BOX on state migrated from
authorization-and-posting-core/v2. FROZEN. gate/migrate.py runs it in the new release's workspace with
PITH_MIGRATION_STATE (the migrated state directory) and PITH_MIGRATION_OBSERVED (what migrations/populate.py saw the
old service acknowledge). Each test starts the new service on its own copy of the migrated state.
"""
import hashlib, json, os, pathlib, shutil, sys, tempfile
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service

STATE = pathlib.Path(os.environ["PITH_MIGRATION_STATE"]); OBS = json.loads(pathlib.Path(os.environ["PITH_MIGRATION_OBSERVED"]).read_text())


@pytest.fixture
def svc():
    d = pathlib.Path(tempfile.mkdtemp(prefix="migrated-")) / "state"; shutil.copytree(STATE, d)
    s = Service(ROOT, db=d / "auth.db").start()
    try: yield s.client
    finally: s.stop()


def keyed(op): return [(int(k.split(":")[0]), int(k.split(":")[1]), v) for k, v in OBS["results"][op].items()]


def canonical(o): return json.dumps(o, sort_keys=True, separators=(",", ":"))


def test_every_acknowledged_decision_is_replayed_identically(svc):
    """Contract: MIG1, Receipts, Idempotency."""
    for acct, rq, v in keyed("authorize"):
        got = svc.authorize(acct, rq, v["amount"])[1]
        assert got == {"request_id": rq, "decision": v["decision"], "available_at_decision": v["available_at_decision"], "replayed": True}, (acct, rq, v, got)


def test_old_releases_and_captures_answer_with_their_receipts(svc):
    """Contract: MIG1, Receipts."""
    for acct, rq, v in keyed("release"):
        assert v["released"] is True and svc.release(acct, rq)[1] == {"request_id": rq, "released": True, "replayed": True}, (acct, rq)
    for acct, rq, v in keyed("capture"):
        assert svc.capture(acct, rq)[1] == {"request_id": rq, "captured": True, "amount": v["amount"], "replayed": True}, (acct, rq, v)
    assert OBS["version_2_answers"]["release_retry"]["released"] is False          # what the same retry was told before the upgrade


def test_accounts_are_kept(svc):
    """Contract: MIG1."""
    for acct, view in OBS["accounts"].items():
        assert svc.account(int(acct))[1] == view, acct


def test_history_is_kept_byte_for_byte_and_continues(svc):
    """Contract: MIG1, EventContract."""
    old = OBS["events"]; _, now = svc.events()
    assert now[:len(old)] == old, "the event history before the upgrade was changed"
    assert svc.authorize(1, 900, 1)[0] == 200
    _, now = svc.events(); prev = "0" * 64
    for e in now:
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        assert e["prev_hash"] == prev and e["hash"] == hashlib.sha256(canonical(body).encode()).hexdigest(), f"chain broken at {e['seq']}"
        prev = e["hash"]
    assert len(now) > len(old) and now[len(old)]["prev_hash"] == old[-1]["hash"]


def test_in_flight_request_is_decided_at_most_once(svc):
    """Contract: MIG1, Idempotency."""
    for f in OBS["in_flight"]:
        first = svc.authorize(f["account"], f["request_id"], f["amount"])[1]; again = svc.authorize(f["account"], f["request_id"], f["amount"])[1]
        assert again == dict(first, replayed=True), (first, again)
        _, evs = svc.events()
        assert sum(e["type"] == "auth.decided" and e["account_id"] == f["account"] and e["request_id"] == f["request_id"] for e in evs) == 1


def test_conflicting_replays_are_still_refused(svc):
    """Contract: MIG1, Idempotency."""
    acct, rq, v = keyed("authorize")[0]
    assert svc.authorize(acct, rq, v["amount"] + 1)[0] in (400, 409)
    assert svc.account(acct)[1] == OBS["accounts"][str(acct)]


def test_new_writes_after_the_upgrade_have_receipts(svc):
    """Contract: Receipts."""
    r = svc.authorize(1, 901, 1)[1]; assert r["decision"] == "AUTHORIZED" and r["replayed"] is False
    assert svc.release(1, 901)[1] == {"request_id": 901, "released": True, "replayed": False}
    assert svc.release(1, 901)[1] == {"request_id": 901, "released": True, "replayed": True}
