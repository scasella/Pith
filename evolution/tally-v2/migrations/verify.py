"""
migrations/verify.py — the version 2 service judged BLACK-BOX on state migrated from version 1. FROZEN.
gate/migrate.py runs it in the new release's workspace with PITH_MIGRATION_STATE (the migrated state directory) and
PITH_MIGRATION_OBSERVED (what migrations/populate.py saw the old service acknowledge). Each test starts the new service
on its own copy of the migrated state, so the tests are independent.
"""
import json, os, pathlib, shutil, sys, tempfile
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


def test_every_recorded_result_is_kept_and_replayed(svc):
    """Contract: M1, Idempotency."""
    c = svc.client
    for rq, v in OBS["results"].items():
        got = c.request(int(rq))[1]
        assert got == {"request_id": int(rq), "counter": "default", "outcome": v["outcome"], "tally": v["tally"], "replayed": True}, (rq, v, got)


def test_version_1_tally_is_counter_default(svc):
    """Contract: M1, T1."""
    c = svc.client
    assert c.tally("default")[1]["tally"] == OBS["tally"] == OBS["bound"]
    assert c.request(900)[1]["outcome"] == "REFUSED"                     # the bound version 1 reached is still reached


def test_in_flight_request_is_decided_once(svc):
    """Contract: M1, T2."""
    c = svc.client
    for rq in OBS["in_flight"]:
        first = c.request(rq)[1]; again = c.request(rq)[1]
        assert again == dict(first, replayed=True), (first, again)
    ids = [int(r) for r in OBS["results"]] + OBS["in_flight"]
    ok = sum(c.request(r)[1]["outcome"] == "OK" for r in ids)
    assert ok == c.tally("default")[1]["tally"] <= OBS["bound"]


def test_old_request_ids_stay_bound_to_their_result(svc):
    """Contract: M1, Idempotency."""
    c = svc.client; rq = int(next(iter(OBS["results"])))
    got = c.request(rq, "other")[1]
    assert got["counter"] == "default" and got["replayed"] is True, got
    assert c.tally("other")[1]["tally"] == 0 and c.request(901, "other")[1]["outcome"] == "OK"
