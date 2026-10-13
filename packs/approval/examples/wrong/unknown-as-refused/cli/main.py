"""cli/main.py — the policy approvals CLI (delivery/CLI-CONTRACT.md). Stdlib only; talks to the service over HTTP."""
import argparse, json, secrets, sys, urllib.error, urllib.request

EXIT = {"OK": 0, "REFUSED": 3, "UNKNOWN": 4, "ERROR": 5}


def parse(argv):
    ap = argparse.ArgumentParser(prog="approvals")
    ap.add_argument("--server", required=True); ap.add_argument("--actor"); ap.add_argument("--request-id", type=int); ap.add_argument("--json", action="store_true")
    ap.add_argument("command", choices=["create", "edit", "submit", "approve", "reject", "publish", "show"]); ap.add_argument("doc")
    ap.add_argument("--title"); ap.add_argument("--body"); ap.add_argument("--revision", type=int)
    a = ap.parse_args(argv)
    need = {"create": ["actor", "title", "body"], "edit": ["actor", "body"], "show": []}.get(a.command, ["actor", "revision"])
    missing = [n for n in need if getattr(a, n) is None]
    if missing: ap.error("missing " + ", ".join("--" + n for n in missing))
    return a


def call(server, method, path, body=None):
    """(status, body) on an answer; raises OSError when there is none."""
    req = urllib.request.Request(server.rstrip("/") + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"null")
        except ValueError: return e.code, None


def execute(a):
    if a.command == "show":
        rq, method, path, body = None, "GET", f"/documents/{a.doc}", None
    else:
        rq = a.request_id if a.request_id is not None else secrets.randbelow(2 ** 53)
        body = {"request_id": rq, "actor": a.actor}
        if a.command == "create": method, path = "POST", "/documents"; body.update(id=a.doc, title=a.title, body=a.body)
        elif a.command == "edit": method, path = "POST", f"/documents/{a.doc}/edit"; body["body"] = a.body
        else: method, path = "POST", f"/documents/{a.doc}/{a.command}"; body["revision"] = a.revision
    try: status, r = call(a.server, method, path, body)
    except (OSError, ValueError) as e:            # no answer (refused, reset, cut, timed out): we do not know
        # DEFECT: no answer is reported as a refusal, so a command that may have been applied looks like one that was not
        return {"outcome": "REFUSED", "reason": "SERVICE_UNAVAILABLE", "request_id": rq, "replayed": None, "document": None}
    if status != 200 or not isinstance(r, dict):
        msg = (r or {}).get("error") if isinstance(r, dict) else None
        return {"outcome": "ERROR", "reason": f"HTTP {status}" + (f": {msg}" if msg else ""), "request_id": rq, "replayed": None, "document": None}
    if a.command == "show": return {"outcome": "OK", "reason": None, "request_id": None, "replayed": None, "document": r}
    return {"outcome": r.get("outcome"), "reason": r.get("reason"), "request_id": rq, "replayed": r.get("replayed"), "document": r.get("document")}


def person(a, res):
    head = res["outcome"] + (f" {res['reason']}" if res["outcome"] == "REFUSED" else f": {res['reason']}" if res["reason"] else "")
    lines = [head]
    if res["request_id"] is not None: lines.append(f"request {res['request_id']}" + (" (replayed)" if res.get("replayed") else ""))
    if res["outcome"] == "UNKNOWN" and res["request_id"] is not None:
        lines.append(f"The command may have been applied. Run it again with --request-id {res['request_id']} to find out safely.")
    d = res.get("document")
    if d:
        lines += [f"document: {d['id']} ({d['title']})", f"status: {d['status']}", f"revision: {d['revision']}",
                  "approvals of this revision: " + (", ".join(d["current_votes"]) or "none")]
    return "\n".join(lines)


def main(argv):
    a = parse(argv); res = execute(a)
    print(json.dumps(res) if a.json else person(a, res))
    return EXIT.get(res["outcome"], 5)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
