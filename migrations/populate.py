"""migrations/populate.py — produce real authorization-and-posting-core/v2 state by driving the OLD judged artifact's own
service. FROZEN. Run by gate/migrate.py in the new release's workspace:
    populate.py --old OLD_WORKSPACE --state DIR --out observed.json
The old service is started by this release's frozen supervisor from the old workspace's service/run.py, on DIR/auth.db.
What it acknowledged (every write's answer, the request in flight when it was killed, the accounts and the whole event
log) is what migrations/verify.py holds the new service to."""
import argparse, json, pathlib, sys, threading, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service

ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--state", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
old = Service(pathlib.Path(a.old), db=pathlib.Path(a.state) / "auth.db").start(); c = old.client
seen = {"authorize": {}, "release": {}, "capture": {}}; v2 = {}


def did(op, acct, rq, res): seen[op][f"{acct}:{rq}"] = res; return res


def body(code_body):
    code, b = code_body; assert code == 200, (code, b); return b


assert c.create(1, 100)[0] == 201 and c.create(2, 50)[0] == 201
for acct, rq, amt in ((1, 1, 30), (1, 2, 90), (1, 3, 20), (1, 4, 40), (2, 1, 50)):       # request id 1 on two accounts
    did("authorize", acct, rq, body(c.authorize(acct, rq, amt)) | {"amount": amt})
did("release", 1, 1, body(c.release(1, 1)))
v2["release_retry"] = body(c.release(1, 1))                  # what version 2 told a client that retried a release
did("capture", 1, 3, body(c.capture(1, 3)))
v2["capture_retry"] = body(c.capture(1, 3))                  # ... and a capture


def _try(rq):
    try: c.authorize(1, rq, 10)
    except Exception: pass
t = threading.Thread(target=_try, args=(6,), daemon=True); t.start(); time.sleep(0.01); old.kill(); t.join(5)   # in flight at SIGKILL
c = old.start().client
did("authorize", 1, 5, body(c.authorize(1, 5, 1)) | {"amount": 1})
did("capture", 2, 1, body(c.capture(2, 1)))
accounts = {str(i): body(c.account(i)) for i in (1, 2)}
code, events = c.events(); assert code == 200
old.stop()
obs = {"format": "pith.migration-observed/v1", "results": seen, "in_flight": [{"account": 1, "request_id": 6, "amount": 10}],
       "accounts": accounts, "events": events, "version_2_answers": v2}
decisions = [r["decision"] for r in seen["authorize"].values()]
assert "DECLINED" in decisions and "AUTHORIZED" in decisions and seen["release"] and seen["capture"], obs
assert v2["release_retry"].get("released") is False, v2                  # the answer version 3 changes on purpose
pathlib.Path(a.out).write_text(json.dumps(obs, indent=1)); print(json.dumps({k: obs[k] for k in ("results", "in_flight", "version_2_answers")}))
