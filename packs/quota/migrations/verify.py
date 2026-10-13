"""
migrations/verify.py — the version 2 library judged BLACK-BOX on dumps migrated from version 1. FROZEN.

gate/migrate.py runs it in the new release's workspace with PITH_MIGRATION_STATE (the directory of migrated dumps)
and PITH_MIGRATION_OBSERVED (what migrations/populate.py saw the OLD library answer, during its activity and when it
loaded each of its own dumps). Every program runs through this release's driver as the candidate (harness/run.py),
starting with `load` of a migrated dump's text, exactly as a deployment hands a stored dump to `Limiter.load`.
The old library's answers to the same calls are version 1's decisions; the new library must give the same ones.
"""
import json, os, pathlib, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import run as R, oracle as O

STATE = pathlib.Path(os.environ["PITH_MIGRATION_STATE"]); OBS = json.loads(pathlib.Path(os.environ["PITH_MIGRATION_OBSERVED"]).read_text())
DUMPS = OBS["dumps"]


def text(name): return (STATE / DUMPS[name]["file"]).read_text()


def answer(r):
    """What is judged of one result: the decision or peek, which error, and a ClockRegression's clock."""
    return (O.comparable(r), r.get("clock") if r.get("error") == "ClockRegression" else None)


def replay(name, probe, before=()):
    """Load the migrated dump into L (after `before`), run one of the old library's probes, compare answer by answer."""
    steps = list(before) + [{"op": "load", "id": "L", "text": text(name)}] + DUMPS[name]["probes"][probe]
    got = R.run(steps, ROOT); n = len(before)
    assert got[n] == {"ok": None}, f"{name}: this version's Limiter.load refused the migrated dump: {got[n]}"
    for i, (g, w) in enumerate(zip(got[n + 1:], DUMPS[name]["answers"][probe])):
        assert answer(g) == answer(w), f"{name} {probe} step {i} {steps[n + 1 + i]}: the upgraded library gave {g}, version 1 gave {w}"
    return got


def test_the_state_is_the_dumps_version_1_made():
    """Contract: MIG1. One migrated file per stored dump, nothing added or removed, each converted (not left as it was)."""
    assert sorted(p.name for p in STATE.iterdir()) == sorted(d["file"] for d in DUMPS.values())
    for name in DUMPS:
        got = R.run([{"op": "load", "id": "L", "text": text(name)}], ROOT)
        assert got == [{"ok": None}], f"{name}: this version's Limiter.load refused the migrated dump: {got[0]}"


@pytest.mark.parametrize("name", sorted(DUMPS))
def test_every_migrated_dump_continues_with_version_1_decisions(name):
    """Contract: MIG1, Persistence, Q1, Q3, Q4. At the dump's clock and later: every peek, grant, remaining count,
    retry hint and refusal is version 1's, the old keys held to the default limit."""
    replay(name, "at_clock"); replay(name, "later")


@pytest.mark.parametrize("name", sorted(n for n in DUMPS if "regress" in DUMPS[n]["probes"]))
def test_earlier_instants_still_regress(name):
    """Contract: MIG1, CLOCK. Every instant before the dump's clock raises ClockRegression naming that clock, and
    changes nothing."""
    replay(name, "regress")


def test_grants_after_a_dump_are_not_invented():
    """Contract: MIG1, Persistence. The old process kept granting after it took "mid" (in flight with respect to that
    dump). Those grants are not in the dump and the upgrade does not invent them: the key has its whole limit, as
    version 1's load of the same dump has."""
    mid = DUMPS["mid"]
    for st in OBS["in_flight"]["mid"]:
        got = R.run([{"op": "load", "id": "L", "text": text("mid")}, {"op": "peek", "id": "L", "key": st["key"], "now": st["now"]},
                     {"op": "acquire", "id": "L", "key": st["key"], "now": st["now"], "cost": mid["limit"]}], ROOT)
        assert got[1:] == [{"ok": mid["limit"]}, {"ok": {"granted": True, "remaining": 0, "retry_after": None}}], \
            f"{st['key']} at {st['now']}: {got[1:]}; the dump was taken before the old process granted {st}"


@pytest.mark.parametrize("name", sorted(DUMPS))
def test_migrated_dumps_have_the_default_limit_only(name):
    """Contract: MIG1, KEYLIMIT. A version 1 dump gains no per-key limits: every key, old or new, has the default."""
    d = DUMPS[name]; keys = d["keys"] + ["fresh", "vip"]
    got = R.run([{"op": "load", "id": "L", "text": text(name)}] + [{"op": "limit_for", "id": "L", "key": k} for k in keys], ROOT)
    assert got[1:] == [{"ok": d["limit"]}] * len(keys), f"{name}: limit_for gave {got[1:]}; version 1's limit was {d['limit']} for every key"


@pytest.mark.parametrize("name", sorted(DUMPS))
def test_migrated_limiter_dumps_and_loads_again(name):
    """Contract: MIG1, Persistence. The upgraded limiter's own dump loads and decides like it (an upgraded deployment
    keeps storing and loading)."""
    replay(name, "redump")


def test_per_key_limits_work_after_the_upgrade():
    """Contract: MIG1, KEYLIMIT, Q1. Next to a limiter loaded from a migrated dump (still version 1's decisions), a
    limiter made anew with per-key limits holds each key to its own limit, as the verified core does."""
    limits = {"vip": 5, "a": 1}
    fresh = [{"op": "new", "id": "N", "limit": 3, "window": 10, "limits": limits},
             {"op": "acquire", "id": "N", "key": "vip", "now": 20, "cost": 4}, {"op": "acquire", "id": "N", "key": "vip", "now": 21},
             {"op": "acquire", "id": "N", "key": "vip", "now": 22}, {"op": "acquire", "id": "N", "key": "a", "now": 22},
             {"op": "acquire", "id": "N", "key": "a", "now": 23}, {"op": "acquire", "id": "N", "key": "b", "now": 23, "cost": 3},
             {"op": "limit_for", "id": "N", "key": "vip"}, {"op": "limit_for", "id": "N", "key": "a"}, {"op": "limit_for", "id": "N", "key": "b"},
             {"op": "dump", "id": "N"}, {"op": "load", "id": "N2", "from": "N"}, {"op": "acquire", "id": "N2", "key": "vip", "now": 31},
             {"op": "acquire", "id": "N2", "key": "a", "now": 31, "cost": 2}]
    got = replay("late", "at_clock", before=fresh)[:len(fresh)]
    want = O.expected({"steps": fresh}, R.runtime(ROOT))
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {fresh[i]}: the upgraded library gave {g}, the contract requires {w}"
    assert got[2]["ok"]["granted"] is True and got[5]["ok"]["granted"] is False, "vip granted past the default, a held to 1"
