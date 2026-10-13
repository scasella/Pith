#!/usr/bin/env python3
"""
experiments/external/counters_check.py — the common external acceptance criteria for the counters task family.

Condition-independent on purpose: it knows nothing of Pith's repository layout, packs or judge. It starts the
subject's service with the command the subject declares (`run.json` in its workspace), talks HTTP to it, kills and
restarts it, and for the change task drives a populated version 1 state through the subject's own migration. Every
condition of the experiment is scored by this file, so a baseline is never failed for lacking Pith's structure.

    python3 counters_check.py --workspace DIR --stage build|change [--previous DIR] [--json]

run.json: {"start": "<argv with {port} and {db}>", "migrate": "<argv with {db}> (change stage)"}; commands run with the
workspace as the working directory. Criteria are named C1.. (build) and D1.. (change); the report lists each.
"""
import argparse, json, os, pathlib, shlex, signal, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error


class Svc:
    def __init__(self, ws, start, db):
        self.ws, self.start_cmd, self.db, self.p = ws, start, db, None
    def start(self):
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        argv = [a.replace("{port}", str(self.port)).replace("{db}", str(self.db)) for a in shlex.split(self.start_cmd)]
        argv = [sys.executable if a in ("python", "python3") else a for a in argv]
        self.p = subprocess.Popen(argv, cwd=self.ws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(200):
            try:
                self.get("/tally"); return self
            except Exception: time.sleep(0.05)
        raise RuntimeError("service did not start")
    def kill(self):
        try: os.killpg(self.p.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        self.p.wait(5)
    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try: self.p.wait(5)
            except subprocess.TimeoutExpired: self.kill()
    def req(self, method, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as x: return x.status, json.loads(x.read() or b"null")
        except urllib.error.HTTPError as e: return e.code, None
    def get(self, path): return self.req("GET", path)
    def post(self, rq, counter=None): return self.req("POST", "/requests", {"request_id": rq, **({"counter": counter} if counter else {})})


def fresh(ws, start):
    d = pathlib.Path(tempfile.mkdtemp(prefix="ext-")); return Svc(ws, start, d / "state.db")


def build_criteria(ws, run):
    out = {}
    s = fresh(ws, run["start"]).start()
    try:
        o = [s.post(i)[1]["outcome"] for i in range(1, 6)]
        out["C1 the bound: three accepted, then refused"] = o == ["OK", "OK", "OK", "REFUSED", "REFUSED"] and s.get("/tally")[1]["tally"] == 3
        a, b = s.post(1)[1], s.post(1)[1]
        out["C2 a repeated request returns the recorded result and changes nothing"] = a == b and a.get("replayed") is True and s.get("/tally")[1]["tally"] == 3
        s.kill(); s.start()
        out["C3 acknowledged results survive a crash"] = s.get("/tally")[1]["tally"] == 3 and s.post(2)[1].get("replayed") is True
        out["C4 malformed input is refused without effect"] = all(s.req("POST", "/requests", x)[0] == 400 for x in ({}, {"request_id": -1}, {"request_id": "x"})) and s.get("/tally")[1]["tally"] == 3
    finally: s.stop()
    s = fresh(ws, run["start"]).start()
    try:
        with __import__("concurrent.futures").futures.ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda i: s.post(100 + i)[1]["outcome"], range(12)))
        out["C5 concurrent requests never pass the bound"] = res.count("OK") == 3 and s.get("/tally")[1]["tally"] == 3
    finally: s.stop()
    return out


def change_criteria(ws, run, previous, prun):
    out = {}
    s = fresh(ws, run["start"]).start()
    try:
        a = [s.post(i, "a")[1]["outcome"] for i in range(1, 5)]; b = s.post(10, "b")[1]["outcome"]
        out["D1 each counter has its own bound"] = a == ["OK", "OK", "OK", "REFUSED"] and b == "OK"
        out["D2 a request without a counter counts against counter default"] = s.post(20)[1].get("counter") == "default" and s.get("/tally?counter=default")[1]["tally"] == 1
        out["D3 a repeat returns the recorded result whatever counter it names"] = s.post(1, "b")[1].get("counter") == "a"
    finally: s.stop()
    # populated state from the subject's own previous (build-stage) service, then the subject's migration
    old = fresh(previous, prun["start"]).start(); db = old.db
    seen = {i: old.post(i)[1] for i in (101, 102, 103, 104)}; old.stop()
    argv = [a.replace("{db}", str(db)) for a in shlex.split(run.get("migrate", "false"))]
    argv = [sys.executable if a in ("python", "python3") else a for a in argv]
    m = subprocess.run(argv, cwd=ws, capture_output=True, text=True)
    out["D4 the migration runs on populated version 1 state"] = m.returncode == 0
    if m.returncode == 0:
        s = Svc(ws, run["start"], db).start()
        try:
            out["D5 every version 1 result is kept and replayed"] = all(
                (lambda r: r.get("replayed") is True and r.get("outcome") == v["outcome"] and r.get("counter") == "default")(s.post(i)[1]) for i, v in seen.items())
            out["D6 the version 1 bound stays reached for counter default"] = s.get("/tally?counter=default")[1]["tally"] == 3 and s.post(900)[1]["outcome"] == "REFUSED"
        finally: s.stop()
    else:
        out["D5 every version 1 result is kept and replayed"] = False; out["D6 the version 1 bound stays reached for counter default"] = False
    out.update({f"regression: {k}": v for k, v in build_criteria(ws, run).items() if not k.startswith("C1")})   # still true after the change
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", required=True); ap.add_argument("--stage", choices=("build", "change"), required=True)
    ap.add_argument("--previous"); ap.add_argument("--json", action="store_true"); a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    try:
        run = json.loads((ws / "run.json").read_text())
        res = build_criteria(ws, run) if a.stage == "build" else change_criteria(ws, run, pathlib.Path(a.previous).resolve(), json.loads((pathlib.Path(a.previous) / "run.json").read_text()))
        err = None
    except Exception as e: res, err = {}, f"{type(e).__name__}: {e}"
    rep = {"format": "pith.external-check/v1", "stage": a.stage, "criteria": res, "error": err, "passed": bool(res) and err is None and all(res.values())}
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for k, v in res.items(): print(f"[{'pass' if v else 'FAIL'}] {k}")
        print(f"external {a.stage}: {'passed' if rep['passed'] else 'NOT passed'}" + (f" ({err})" if err else ""))
    sys.exit(0 if rep["passed"] else 1)


if __name__ == "__main__":
    main()
