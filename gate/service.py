"""
gate/service.py — start a candidate's process the way the evaluator starts anything of the candidate's. FROZEN.
Domain-free: a pack harness says WHAT to start (an argv in the judged workspace) and how readiness is observed (an
HTTP path); this module owns HOW: a port it chooses, a state directory it creates and hands to the candidate's
identity (the only place the candidate may write), a scrubbed environment, a new session, the resource limits and
privilege drop of gate/sandbox.py, crash simulation (SIGKILL of the whole process group) and restart on the same state.

    with Supervised(root, ["node", "service/run.mjs", "--port", "{port}", "--db", "{state}/db"], ready="/health") as s:
        s.url("/things")                                     # http://127.0.0.1:<port>/things
        s.kill(); s.start()                                  # crash, then restart on the same state directory

Added in v0.8.0 (M3): the second and third packs both needed it, and the root pack's own service supervisor
already did the same thing for one fixed entrypoint.
"""
import os, pathlib, socket, subprocess, tempfile, time, urllib.request, urllib.error
try: from gate import sandbox as SB             # imported by a pack harness (release root on sys.path)
except ImportError: import sandbox as SB        # imported from inside gate/


class Supervised:
    def __init__(self, root, argv, ready="/", env=None, state=None, limits=None):
        self.limits = dict(limits or {})                     # overrides of gate/sandbox.py LIMITS (None lifts one); recorded in self.applied_limits
        self.root = pathlib.Path(root); self.argv = list(argv); self.ready = ready; self.env = dict(env or {})
        self.state = pathlib.Path(state) if state else pathlib.Path(tempfile.mkdtemp(prefix="judged-state-"))
        self.proc = None; self.port = None; self.log = None

    def url(self, path=""): return f"http://127.0.0.1:{self.port}{path}"

    def _free_port(self):
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

    def start(self, timeout=20.0):
        self.port = self._free_port()
        ident = SB.candidate_identity()
        if ident: os.chown(self.state, *ident); self.state.chmod(0o700)
        argv = [a.replace("{port}", str(self.port)).replace("{state}", str(self.state)) for a in self.argv]
        self.logpath = self.state.parent / f"{self.state.name}-{self.port}.log"; self.log = open(self.logpath, "ab")
        self.proc = subprocess.Popen(argv, cwd=self.root, env=SB.scrubbed_env(self.env), stdout=self.log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, preexec_fn=SB.demote(ident, self.limits))
        self.applied_limits = SB.limits(self.limits)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None: raise RuntimeError(f"candidate process exited early (code {self.proc.returncode}); see {self.logpath}")
            try:
                with urllib.request.urlopen(self.url(self.ready), timeout=2) as r:
                    if r.status == 200: return self
            except (urllib.error.URLError, OSError): pass
            time.sleep(0.1)
        self.stop(); raise RuntimeError(f"candidate process did not become ready at {self.ready}; see {self.logpath}")

    def kill(self):
        """A crash: SIGKILL to the whole process group, no shutdown hooks; the candidate cannot outlive it."""
        if self.proc and self.proc.poll() is None:
            try: os.killpg(self.proc.pid, 9)
            except ProcessLookupError: pass
            self.proc.wait(timeout=10)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired: self.kill()
        if self.proc:
            try: os.killpg(self.proc.pid, 9)
            except (ProcessLookupError, PermissionError): pass
        if self.log: self.log.close(); self.log = None

    def restart(self): self.stop(); return self.start()
    def __enter__(self): return self.start()
    def __exit__(self, *a): self.stop()
