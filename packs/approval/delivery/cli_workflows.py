"""
delivery/cli_workflows.py — application delivery for pith.approval, through the candidate's CLI. FROZEN.

Runs the candidate's CLI (harness/supervisor.py cli: as the candidate's user, under its limits) against the
candidate's service, started as a separate process by the evaluator, through the commands of CLI-CONTRACT.md:
workflows AW1–AW5, and interaction obligations AI1–AI3 with faults injected by the judge (a proxy it owns that drops
a response after the service answered it, and an address where nothing listens). Every outcome is judged from the
exit code, the output the contract names, and the service's own state read with the frozen client.
Status: passed | failed.
"""
import http.client, http.server, json, pathlib, re, socket, sys, threading, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service, cli


class Proxy:
    """A judge-owned HTTP proxy in front of the service. drop_next(): the next POST is forwarded and answered by the
    service, and then the connection is closed without the answer (a response lost after commit)."""
    def __init__(self, upstream):
        u = urllib.parse.urlparse(upstream); self.up = (u.hostname, u.port); self.drops = 0; self.dropped = []
        outer = self
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def relay(self):
                n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
                c = http.client.HTTPConnection(*outer.up, timeout=10)
                c.request(self.command, self.path, body=body, headers={"Content-Type": self.headers.get("Content-Type") or "application/json"})
                r = c.getresponse(); data = r.read(); c.close()
                if self.command == "POST" and outer.drops:
                    outer.drops -= 1; outer.dropped.append((self.path, r.status, data))
                    self.close_connection = True
                    try: self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    return
                self.send_response(r.status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
            do_GET = do_POST = relay
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def url(self): return f"http://127.0.0.1:{self.srv.server_address[1]}"
    def drop_next(self): self.drops = 1
    def close(self): self.srv.shutdown(); self.srv.server_close()


def dead_url():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return f"http://127.0.0.1:{port}"


class Run:
    def __init__(self, code, out, err, args): self.code, self.out, self.err, self.args = code, out or "", err or "", args
    def json(self):
        try: return json.loads(self.out)
        except ValueError: return None
    def first(self): return (self.out.strip().splitlines() or [""])[0]
    def brief(self): return f"`{' '.join(self.args)}` exit {self.code}; " + (self.out.strip()[:160] or self.err.strip()[:160]).replace("\n", " / ")


class Driver:
    def __init__(self, server): self.server = server; self.log = []
    def run(self, *args, actor=None, rq=None, js=True, server=None):
        a = ["--server", server or self.server] + (["--actor", actor] if actor else []) + (["--request-id", str(rq)] if rq is not None else []) + (["--json"] if js else []) + list(map(str, args))
        code, out, err = cli(a); r = Run(code, out, err, a); self.log.append(r.brief()); return r


def outcome(r): j = r.json(); return j and j.get("outcome")


def step(results, wid, ok, evidence):
    results.append({"obligation": wid, "ok": bool(ok), "evidence": evidence})
    return ok


def workflows(d, c, results):
    # AW1 create and show
    r1 = d.run("create", "aw1", "--title", "Leave policy", "--body", "v1", actor="alice")
    s = d.run("show", "aw1"); h = d.run("show", "aw1", js=False)
    doc = (s.json() or {}).get("document") or {}
    step(results, "AW1", r1.code == 0 and outcome(r1) == "OK" and s.code == 0 and doc.get("status") == "draft" and doc.get("revision") == 1
         and "status: draft" in h.out and "revision: 1" in h.out and c.document("aw1")[1].get("status") == "draft",
         f"{r1.brief()} | {s.brief()} | person: {h.out.strip()[:120]!r}")

    # AW2 the review path
    runs = [d.run("create", "aw2", "--title", "Travel", "--body", "v1", actor="alice"), d.run("submit", "aw2", "--revision", 1, actor="alice"),
            d.run("approve", "aw2", "--revision", 1, actor="bob"), d.run("approve", "aw2", "--revision", 1, actor="carol"),
            d.run("publish", "aw2", "--revision", 1, actor="dave")]
    h = d.run("show", "aw2", js=False); svc = c.document("aw2")[1]
    step(results, "AW2", all(r.code == 0 and outcome(r) == "OK" for r in runs) and svc.get("status") == "published" and "status: published" in h.out,
         " | ".join(r.brief() for r in runs) + f" | service status {svc.get('status')}")

    # AW3 refusals are named
    d.run("create", "aw3", "--title", "Expenses", "--body", "v1", actor="bob"); d.run("submit", "aw3", "--revision", 1, actor="bob")
    sod = d.run("approve", "aw3", "--revision", 1, actor="bob"); stale = d.run("approve", "aw3", "--revision", 7, actor="carol")
    person = d.run("approve", "aw3", "--revision", 1, actor="bob", js=False)
    svc = c.document("aw3")[1]
    step(results, "AW3", sod.code == 3 and (sod.json() or {}).get("reason") == "SEPARATION_OF_DUTIES" and stale.code == 3 and (stale.json() or {}).get("reason") == "STALE_REVISION"
         and person.code == 3 and re.match(r"REFUSED\s+SEPARATION_OF_DUTIES\b", person.first()) and svc.get("current_votes") == [],
         f"{sod.brief()} | {stale.brief()} | person first line {person.first()!r}")

    # AW4 an edit restarts review
    d.run("create", "aw4", "--title", "Security", "--body", "v1", actor="alice"); d.run("submit", "aw4", "--revision", 1, actor="alice")
    d.run("approve", "aw4", "--revision", 1, actor="carol")
    e = d.run("edit", "aw4", "--body", "v2", actor="bob"); old = d.run("approve", "aw4", "--revision", 1, actor="alice")
    doc = (e.json() or {}).get("document") or {}; svc = c.document("aw4")[1]
    step(results, "AW4", e.code == 0 and doc.get("revision") == 2 and doc.get("status") == "draft" and doc.get("current_votes") == [] and old.code == 3
         and (old.json() or {}).get("reason") == "STALE_REVISION" and svc.get("revision") == 2 and svc.get("current_votes") == [],
         f"{e.brief()} | {old.brief()}")

    # AW5 errors are not refusals
    nf = d.run("approve", "no-such-doc", "--revision", 1, actor="bob"); us = d.run("approve", "aw4", "--revision", 2)   # no --actor
    step(results, "AW5", nf.code == 5 and outcome(nf) == "ERROR" and us.code == 2, f"{nf.brief()} | {us.brief()}")


def interactions(d, c, svc_url, results):
    # AI1 a response lost after commit
    p = Proxy(svc_url)
    try:
        d.run("create", "ai1", "--title", "Data", "--body", "v1", actor="alice"); d.run("submit", "ai1", "--revision", 1, actor="alice")
        p.drop_next(); lost = d.run("approve", "ai1", "--revision", 1, actor="bob", server=p.url())
        p.drop_next(); lost_h = d.run("approve", "ai1", "--revision", 1, actor="carol", server=p.url(), js=False)
    finally: p.close()
    j = lost.json() or {}; rq = j.get("request_id")
    after = c.document("ai1")[1]
    retry = d.run("approve", "ai1", "--revision", 1, actor="bob", rq=rq) if isinstance(rq, int) else None
    m = re.search(r"--request-id\s+(\d+)", lost_h.out)
    retry_h = d.run("approve", "ai1", "--revision", 1, actor="carol", rq=int(m[1])) if m else None
    final = c.document("ai1")[1]
    committed = after.get("current_votes") == ["bob", "carol"]
    step(results, "AI1", lost.code == 4 and j.get("outcome") == "UNKNOWN" and j.get("document") is None and committed
         and retry is not None and retry.code == 0 and (retry.json() or {}).get("replayed") is True
         and lost_h.code == 4 and lost_h.first().startswith("UNKNOWN") and retry_h is not None and retry_h.code == 0
         and final.get("current_votes") == ["bob", "carol"] and final.get("status") == "approved"
         and [a["actor"] for a in final.get("approvals", [])] == ["bob", "carol"],
         f"lost: {lost.brief()} | person: {lost_h.out.strip()[:160]!r} | committed before retry: {after.get('current_votes')} | "
         f"retry: {retry.brief() if retry else 'no request id to retry with'} | person retry: {retry_h.brief() if retry_h else 'no --request-id in the output'} | final votes {final.get('current_votes')}")

    # AI2 an unreachable service
    dead = dead_url()
    runs = [d.run("show", "ai1", server=dead), d.run("approve", "ai1", "--revision", 1, actor="bob", server=dead),
            d.run("create", "ai2", "--title", "X", "--body", "v1", actor="alice", server=dead, js=False)]
    step(results, "AI2", all(r.code == 4 for r in runs) and outcome(runs[1]) == "UNKNOWN", " | ".join(r.brief() for r in runs))

    # AI3 fresh request ids
    d.run("create", "ai3", "--title", "Y", "--body", "v1", actor="bob"); d.run("submit", "ai3", "--revision", 1, actor="bob")
    a1 = d.run("approve", "ai3", "--revision", 1, actor="alice"); a2 = d.run("approve", "ai3", "--revision", 1, actor="carol")
    ids = [(r.json() or {}).get("request_id") for r in (a1, a2)]; svc = c.document("ai3")[1]
    step(results, "AI3", a1.code == 0 and a2.code == 0 and ids[0] != ids[1] and svc.get("current_votes") == ["alice", "carol"],
         f"{a1.brief()} | {a2.brief()} | request ids {ids} | service votes {svc.get('current_votes')}")


def run(out_dir=None):
    results = []; svc = Service().start()
    try:
        c = svc.client
        for aid, roles in (("alice", ["editor", "approver"]), ("bob", ["editor", "approver"]), ("carol", ["approver"]), ("dave", ["publisher"])):
            c.actor(aid, roles)
        d = Driver(svc.url())
        workflows(d, c, results); interactions(d, c, svc.url(), results)
    finally: svc.stop()
    if out_dir:
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True); (pathlib.Path(out_dir) / "cli-runs.txt").write_text("\n".join(d.log) + "\n")
    return {"status": "passed" if all(r["ok"] for r in results) else "failed", "results": results, "runs": len(d.log)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
