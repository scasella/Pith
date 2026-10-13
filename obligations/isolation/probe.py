"""
obligations/isolation/probe.py — FROZEN. Run by the judge under the candidate's identity and limits
(supervisor.run_as_candidate) before any candidate code runs. It tries what a hostile candidate would try and prints
one JSON object saying what was reachable. The judge treats "denied" as the only acceptable answer for each item;
anything reachable is reported by name and the isolation status is "not enforced".

    python -I probe.py --evidence DIR --policy DIR [--secret PATH ...] [--host HOST:PORT ...]
"""
import argparse, json, os, pathlib, socket

ap = argparse.ArgumentParser()
ap.add_argument("--evidence", required=True); ap.add_argument("--policy", required=True)
ap.add_argument("--secret", action="append", default=[]); ap.add_argument("--host", action="append", default=[])
a = ap.parse_args()
res = {"uid": os.getuid(), "euid": os.geteuid(), "groups": os.getgroups(), "checks": {}}

def attempt(name, fn):
    try: fn(); res["checks"][name] = "reachable"
    except (PermissionError, FileNotFoundError, OSError, socket.timeout) as e: res["checks"][name] = f"denied ({type(e).__name__})"

attempt("read evidence directory", lambda: os.listdir(a.evidence))
attempt("write evidence directory", lambda: (pathlib.Path(a.evidence) / ".probe").write_text("x"))
for d in ("kernel", "obligations", "gate"):
    attempt(f"write policy ({d}/)", lambda d=d: (pathlib.Path(a.policy) / d / ".probe").write_text("x"))
attempt("modify gate code", lambda: open(pathlib.Path(a.policy) / "gate" / "app_gate.py", "a").close())
for sec in a.secret:
    attempt(f"read {sec}", lambda sec=sec: pathlib.Path(sec).read_bytes())
for hp in a.host:
    h, p = hp.rsplit(":", 1)
    attempt(f"connect {hp}", lambda h=h, p=p: socket.create_connection((h, int(p)), timeout=3).close())
res["checks"]["runs as root"] = "reachable" if os.geteuid() == 0 else "denied (unprivileged)"
print(json.dumps(res))
