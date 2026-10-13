"""migrations/populate.py — produce real approval-workflow/v1 state by driving the OLD judged artifact's own service.
FROZEN. Run by gate/migrate.py in the new release's workspace:

    populate.py --old OLD_WORKSPACE --state DIR --out observed.json

The old service is started the way the old release started it (its app.manifest.yaml runtime; harness/SERVICE.md) on
DIR/approval.db, and driven through the version 1 API only (no quorum anywhere). It leaves: actors with every role
(and one with none); documents in draft, in review with one approval, approved, rejected and published; a document
edited after two approvals (their approvals stale, kept as history) and in review again; refusals for several rules;
and one approval in flight when the old service is SIGKILLed (sent, then the process group killed before or while it
answers). What the old service acknowledged is written to observed.json, which migrations/verify.py holds the new
service to: every result with the command that produced it, the in-flight command, and, read back from the old
service after a restart, every document, the actors and the event log.
"""
import argparse, json, pathlib, sys, threading, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service
from harness.client import Client

ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--state", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
ACTORS = {"alice": ["editor", "approver"], "bob": ["editor", "approver"], "carol": ["approver"], "dave": ["publisher"], "erin": ["approver"], "zed": []}
old = Service(pathlib.Path(a.old), state=pathlib.Path(a.state)).start()
results, commands = {}, {}
N = iter(range(1001, 2000))


def run(c, op, doc, actor, revision=None, rq=None, **kw):
    rq = rq or next(N)
    cmd = {"op": op, "doc": doc, "actor": actor, **({"revision": revision} if revision is not None else {}), **kw}
    code, r = send(c, rq, cmd)
    assert code == 200, (cmd, code, r)
    results[str(rq)] = r; commands[str(rq)] = cmd
    return r


def send(c, rq, cmd, timeout=10):
    if cmd["op"] == "create": return c._req("POST", "/documents", {"request_id": rq, "id": cmd["doc"], "actor": cmd["actor"], "title": cmd["title"], "body": cmd["body"]}, timeout=timeout)
    if cmd["op"] == "edit": return c._req("POST", f"/documents/{cmd['doc']}/edit", {"request_id": rq, "actor": cmd["actor"], "body": cmd["body"]}, timeout=timeout)
    return c._req("POST", f"/documents/{cmd['doc']}/{cmd['op']}", {"request_id": rq, "actor": cmd["actor"], "revision": cmd["revision"]}, timeout=timeout)


def create(c, doc, actor): return run(c, "create", doc, actor, title=f"{doc} policy", body=f"{doc}, revision 1")


c = old.client
for who, roles in ACTORS.items(): assert c.actor(who, roles)[0] == 201
create(c, "d-draft", "alice")                                                                        # draft
create(c, "d-review", "alice"); run(c, "submit", "d-review", "alice", 1); run(c, "approve", "d-review", "bob", 1)    # in review, one approval
create(c, "d-approved", "bob"); run(c, "submit", "d-approved", "bob", 1)
run(c, "approve", "d-approved", "alice", 1); run(c, "approve", "d-approved", "carol", 1)              # approved
create(c, "d-rejected", "bob"); run(c, "submit", "d-rejected", "bob", 1); run(c, "reject", "d-rejected", "erin", 1)  # rejected
create(c, "d-published", "alice"); run(c, "submit", "d-published", "alice", 1)
run(c, "approve", "d-published", "bob", 1); run(c, "approve", "d-published", "erin", 1)
create(c, "d-stale", "alice"); run(c, "submit", "d-stale", "alice", 1)
run(c, "approve", "d-stale", "bob", 1); run(c, "approve", "d-stale", "carol", 1)                      # approved, then edited:
run(c, "edit", "d-stale", "bob", body="d-stale, revision 2"); run(c, "submit", "d-stale", "bob", 2)  # both approvals are stale history
run(c, "approve", "d-stale", "erin", 2)                                                              # in review, one current approval
# refusals, each recorded and replayable
for r, want in ((run(c, "create", "d-nope", "carol", title="t", body="b"), "ROLE"),
                (run(c, "approve", "d-review", "alice", 1), "SEPARATION_OF_DUTIES"),
                (run(c, "approve", "d-review", "bob", 1), "ALREADY_APPROVED"),
                (run(c, "approve", "d-stale", "carol", 1), "STALE_REVISION"),
                (run(c, "publish", "d-review", "dave", 1), "WRONG_STATE"),
                (run(c, "submit", "d-draft", "bob", 1), "NOT_AUTHOR")):
    assert (r["outcome"], r["reason"]) == ("REFUSED", want), (r, want)
# a command in flight when the old service dies: the approval that would reach d-flight's quorum
create(c, "d-flight", "alice"); run(c, "submit", "d-flight", "alice", 1); run(c, "approve", "d-flight", "bob", 1)
flight = {"rq": 1999, "cmd": {"op": "approve", "doc": "d-flight", "actor": "carol", "revision": 1}}


def _try():
    try: send(Client(old.url()), flight["rq"], flight["cmd"], timeout=3)
    except Exception: pass


t = threading.Thread(target=_try, daemon=True); t.start(); time.sleep(0.01); old.kill(); t.join(5)
c = old.start().client                                                                               # the old service restarts on its state
run(c, "publish", "d-published", "dave", 1)                                                          # published, after the restart
docs = {d: c.document(d)[1] for d in ("d-draft", "d-review", "d-approved", "d-rejected", "d-published", "d-stale", "d-flight")}
obs = {"format": "pith.migration-observed/v1", "results": results, "commands": commands, "in_flight": [flight],
       "documents": docs, "actors": c.actors()[1], "events": c.events()[1]}
old.stop()
st = {d: v["status"] for d, v in docs.items()}
assert st["d-draft"] == "draft" and st["d-review"] == "in_review" and st["d-approved"] == "approved" and st["d-rejected"] == "rejected" and st["d-published"] == "published", st
assert st["d-stale"] == "in_review" and docs["d-stale"]["revision"] == 2 and len(docs["d-stale"]["approvals"]) == 3 and docs["d-stale"]["current_votes"] == ["erin"], docs["d-stale"]
assert all("quorum" not in d for d in docs.values()), "the old service is not a version 1 service"
pathlib.Path(a.out).write_text(json.dumps(obs, indent=1)); print(json.dumps({k: (len(v) if isinstance(v, (dict, list)) else v) for k, v in obs.items()}))
