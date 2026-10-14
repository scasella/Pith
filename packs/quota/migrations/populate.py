"""migrations/populate.py — produce real sliding-window-quota/v1 state by driving the OLD judged artifact's own library.
FROZEN. Run by gate/migrate.py in the new release's workspace, as the judge:

    python3 -I migrations/populate.py --old OLD_WORKSPACE --state DIR --out observed.json

A library has no service and no database: the durable state of a deployment is the text `dump()` returned, which it
stores and later hands to `Limiter.load` (LW4). So the state is a directory of stored dumps, one `<name>.dump` file
each, and the OLD library produces them: the old release's own frozen driver (harness/driver.py or driver.mjs in
OLD_WORKSPACE, by its app.manifest.yaml) runs as the candidate's user, the way the old release's harness runs it
(gate/sandbox.py:run_as_candidate_full). Activity on several keys: grants, a denial with a retry hint, a request that
can never fit, peeks, a clock advanced past grants, grants about to expire, dumps taken in the middle of activity
(the limiter keeps granting after a dump: those grants are "in flight" with respect to it), a dump of a limiter that
was itself loaded from a dump, and the extremes of the domain.

`observed` records what the old library answered during the activity and, for each dump, what the old library
answers NEXT when it loads that dump (`probes`): every later decision migrations/verify.py holds the new library to.
The probes use only version 1's API, so they are version 1's answers by construction.
"""
import argparse, json, pathlib, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate import sandbox as SB

ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--state", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
OLD = pathlib.Path(a.old).resolve(); STATE = pathlib.Path(a.state)
U31, U53 = 2 ** 31 - 1, 2 ** 53 - 1

# the old release's harness/run.py: its driver per runtime, and the limits it runs them under
manifest = OLD / "app.manifest.yaml"
RT = ((yaml.safe_load(manifest.read_text()) or {}) if manifest.exists() else {}).get("runtime") or "python"
DRIVER = {"python": [sys.executable, "-I", "harness/driver.py"], "node": ["node", "harness/driver.mjs"]}[RT]
LIMITS = {"python": {}, "node": {"RLIMIT_AS": None}}[RT]


def run(steps):
    code, out, err = SB.run_as_candidate_full(DRIVER + [json.dumps({"steps": steps})], cwd=OLD, timeout=120, limits=LIMITS)
    lines = [l for l in (out or "").splitlines() if l.startswith('{"results"')]
    if code != 0 or len(lines) != 1: sys.exit(f"the old library's driver failed: exit {code}; stdout {out[-400:]!r}; stderr {err[-800:]!r}")
    res = json.loads(lines[0])["results"]
    assert len(res) == len(steps), (len(res), len(steps))
    return res


def acq(key, now, cost=1, id="A"): return {"op": "acquire", "id": id, "key": key, "now": now, "cost": cost}
def peek(key, now, id="A"): return {"op": "peek", "id": id, "key": key, "now": now}


# ---- activity: one process, three limiters, dumps in the middle of it ------------------------------------------------
activity = [
    {"op": "new", "id": "A", "limit": 3, "window": 10},
    acq("a", 0), acq("a", 2, 2),
    acq("a", 4),                          # denied: the grant at 0 must expire first (retry hint 6)
    acq("b", 5, 3),
    acq("c", 5, 4),                       # 4 > 3: can never fit (no retry hint)
    peek("a", 6),                         # the clock (6) moves past the latest grant (5)
    {"op": "dump", "id": "A", "name": "mid"},
    acq("d", 7, 2),                       # granted AFTER "mid" was taken: in flight with respect to it
    acq("a", 9),                          # denied; the grant at 0 still counts at 9 and stops at 10
    {"op": "dump", "id": "A", "name": "edge"},     # a grant (a at 0) in its last counting instant
    acq("a", 12), acq("b", 13),           # past two expiries; b still held by its grant at 5
    peek("b", 14),
    {"op": "dump", "id": "A", "name": "late"},
    {"op": "new", "id": "B", "limit": 1, "window": 1},
    acq("x", 100, id="B"), acq("x", 100, id="B"),
    {"op": "dump", "id": "B", "name": "tight"},    # the shortest window: the grant counts only at the clock itself
    {"op": "new", "id": "C", "limit": 5, "window": 60},
    {"op": "dump", "id": "C", "name": "empty"},    # nothing granted, clock 0
    {"op": "new", "id": "Z", "limit": U31, "window": U31},
    acq("k", U53 - U31, U31, id="Z"), acq("k", U53 - U31 + 7, id="Z"),
    {"op": "dump", "id": "Z", "name": "extreme"},  # the largest limit, window and instants
]
names = {i: s.pop("name") for i, s in enumerate(activity) if s["op"] == "dump"}
results = run(activity)
texts = {}
for i, name in names.items():
    r = results[i]
    if not (r.get("ok") or {}).get("type") == "str": sys.exit(f"the old library's dump() did not return text: {r}")
    texts[name] = r["ok"]["text"]

# a limiter loaded from a dump (LW4: state handed to another process) that keeps granting, then is dumped
handed_steps = [{"op": "load", "id": "E", "text": texts["mid"]}, acq("e", 8, 2, id="E"), acq("a", 8, id="E"), {"op": "dump", "id": "E"}]
handed = run(handed_steps)
texts["handed"] = handed[3]["ok"]["text"]

CONFIG = {"mid": (3, 10, 6, ["a", "b", "c"]), "edge": (3, 10, 9, ["a", "b", "c", "d"]), "late": (3, 10, 14, ["a", "b", "c", "d"]),
          "tight": (1, 1, 100, ["x"]), "empty": (5, 60, 0, []), "extreme": (U31, U31, U53 - U31 + 7, ["k"]), "handed": (3, 10, 8, ["a", "b", "e"])}


def probes(limit, window, clock, keys):
    """What verify asks of a limiter loaded from the dump: each a program run after `load` into limiter L."""
    every = keys + ["fresh"]
    at_clock = []
    for k in every: at_clock += [peek(k, clock, "L"), acq(k, clock, 1, "L"), acq(k, clock, limit, "L"), acq(k, clock, limit + 1, "L")]
    later = []
    for dt in sorted({1, window - 1, window} - {0}):
        if clock + dt <= U53:
            for k in every: later += [peek(k, clock + dt, "L"), acq(k, clock + dt, 1, "L")]
    out = {"at_clock": at_clock, "later": later,
           "redump": [{"op": "dump", "id": "L"}, {"op": "load", "id": "M", "from": "L"}] + [peek(k, clock, "M") for k in every]}
    if clock > 0:                                  # every instant before the dump's clock is a regression; nothing changes
        out["regress"] = [acq(k, clock - 1, 1, "L") for k in every] + [peek("fresh", clock - 1, "L"), peek("fresh", 0, "L"), acq("fresh", clock, 1, "L")]
    return out


observed = {"format": "pith.migration-observed/v1", "runtime": RT,
            "activity": [{"step": s, "result": r} for s, r in zip(activity, results)],
            "handed": [{"step": dict(s, text="<mid>") if "text" in s else s, "result": r} for s, r in zip(handed_steps, handed)],
            "in_flight": {"mid": [acq("d", 7, 2)]},        # granted by the old process after "mid" was dumped: not in "mid"
            "dumps": {}}
STATE.mkdir(parents=True, exist_ok=True)
for name, text in texts.items():
    (STATE / f"{name}.dump").write_text(text)
    limit, window, clock, keys = CONFIG[name]
    P = probes(limit, window, clock, keys); answers = {}
    for pname, steps in P.items():
        got = run([{"op": "load", "id": "L", "text": text}] + steps)
        if got[0] != {"ok": None}: sys.exit(f"the old library does not load its own dump {name}: {got[0]}")
        answers[pname] = got[1:]
    observed["dumps"][name] = {"file": f"{name}.dump", "limit": limit, "window": window, "clock": clock, "keys": keys,
                               "version_1_text": text, "probes": P, "answers": answers}

# what the activity must have produced, or the verify step would prove less than it says
dec = [r["ok"] for s, r in zip(activity, results) if s["op"] == "acquire"]
assert any(d["granted"] is False and d["retry_after"] for d in dec), "a denial with a retry hint"
assert any(d["granted"] is False and d["retry_after"] is None for d in dec), "a request that can never fit"
assert observed["dumps"]["mid"]["answers"]["at_clock"][0] == {"ok": 0}, "in mid, a has used its whole limit at the clock"
assert results[8]["ok"]["granted"] is True, "the in-flight grant was made by the old process"
pathlib.Path(a.out).write_text(json.dumps(observed, indent=1))
print(json.dumps({"runtime": RT, "dumps": {n: len(t) for n, t in texts.items()}}))
