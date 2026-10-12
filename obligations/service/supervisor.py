"""
obligations/service/supervisor.py — the judge's only way of touching candidate code. FROZEN.

The candidate's service is started as a SEPARATE PROCESS from a fixed entrypoint (service/run.py) with a scrubbed
environment, isolated interpreter (-I), a port the supervisor chooses and a database path the supervisor owns.
The judge never imports candidate Python. Everything the judge learns comes from HTTP responses it observed itself
through the frozen client. The supervisor can kill the process mid-flight and restart it on the same database,
which is how crash-window and durability obligations are exercised black-box.

Candidate contract (service/run.py):  python -I service/run.py --port <int> --db <path>
  serves the generated OpenAPI on 127.0.0.1:<port>, the UI at /, and exits on SIGTERM.
"""
import os, pathlib, socket, subprocess, sys, tempfile, time
from .client import Client

SCRUBBED_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")

class Service:
    def __init__(self, root: pathlib.Path, db: pathlib.Path | None = None):
        self.root = pathlib.Path(root); self.db = pathlib.Path(db) if db else pathlib.Path(tempfile.mkdtemp(prefix="judged-db-")) / "state.db"
        self.proc = None; self.port = None; self.log = None; self.client = None
    def _free_port(self):
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]
    def start(self, timeout=20.0):
        self.port = self._free_port()
        env = {k: os.environ[k] for k in SCRUBBED_ENV_KEYS if k in os.environ}
        env["SEED_KERNEL_PY"] = str(self.root / "kernel" / "core" / "py" / "authcore-py")   # where the translated core lives; nothing else is told to the candidate
        self.logpath = self.db.parent / f"service-{self.port}.log"; self.log = open(self.logpath, "ab")
        self.proc = subprocess.Popen([sys.executable, "-I", "service/run.py", "--port", str(self.port), "--db", str(self.db)],
                                     cwd=self.root, env=env, stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self.client = Client(f"http://127.0.0.1:{self.port}")
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None: raise RuntimeError(f"candidate service exited early (code {self.proc.returncode}); see {self.logpath}")
            try:
                code, _ = self.client.events(); 
                if code == 200: return self
            except Exception: pass
            time.sleep(0.1)
        self.stop(); raise RuntimeError("candidate service did not become ready")
    def kill(self):
        """Simulate a crash: SIGKILL, no shutdown hooks."""
        if self.proc and self.proc.poll() is None: self.proc.kill(); self.proc.wait(timeout=10)
    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait(timeout=5)
        if self.log: self.log.close()
    def restart(self):
        self.stop(); return self.start()
    def __enter__(self): return self.start()
    def __exit__(self, *a): self.stop()
