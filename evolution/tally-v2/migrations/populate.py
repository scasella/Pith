"""migrations/populate.py — produce real tally/v1 state by driving the OLD judged artifact's own service. FROZEN.
Run by gate/migrate.py in the new release's workspace:  populate.py --old OLD_WORKSPACE --state DIR --out observed.json
What it observed (results the old service acknowledged, the request in flight when it was killed, its final tally) is
what migrations/verify.py holds the new service to."""
import argparse, json, pathlib, sys, threading, time, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate.service import Supervised

ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--state", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()


def post(s, rq, timeout=10):
    req = urllib.request.Request(s.url("/requests"), data=json.dumps({"request_id": rq}).encode(), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())


def get(s):
    with urllib.request.urlopen(s.url("/tally"), timeout=10) as r: return json.loads(r.read())


old = Supervised(a.old, [sys.executable, "-I", "service/run.py", "--port", "{port}", "--db", "{state}/tally.db"], ready="/tally", state=a.state).start()
seen = {}
for rq in (101, 102): seen[rq] = post(old, rq)
# a request in flight when the old service dies: sent, then SIGKILL before (or while) it answers
def _try(s, rq):
    try: post(s, rq, timeout=3)
    except Exception: pass
t = threading.Thread(target=_try, args=(old, 103), daemon=True); t.start(); time.sleep(0.01); old.kill(); t.join(5)
old.start()
for rq in (104, 105): seen[rq] = post(old, rq)
final = get(old); old.stop()
obs = {"format": "pith.migration-observed/v1", "results": {str(k): v for k, v in seen.items()}, "in_flight": [103], "tally": final["tally"], "bound": final["bound"]}
assert sum(v["outcome"] == "REFUSED" for v in seen.values()) >= 1 and final["tally"] == final["bound"], obs     # a refusal and a full tally carried over
pathlib.Path(a.out).write_text(json.dumps(obs, indent=1)); print(json.dumps(obs))
