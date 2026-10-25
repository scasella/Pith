"""harness/supervisor.py — how this pack starts the candidate's service. FROZEN.

The entrypoint follows app.manifest.yaml:runtime (harness/SERVICE.md); starting, the state directory, the candidate's
identity and limits, crash and restart are the evaluator's (gate/service.py). The harness never imports candidate code.
"""
import os, pathlib, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate.service import Supervised
from gate import sandbox as SB
from harness.client import Client

ENTRY = {"python": [sys.executable, "-I", "service/run.py"], "node": ["node", "service/run.mjs"]}
LIMITS = {"python": {}, "node": {"RLIMIT_AS": None}}     # V8's WebAssembly reservations exceed any useful RLIMIT_AS (gate/sandbox.py limits)


def manifest(root=ROOT):
    p = pathlib.Path(root) / "app.manifest.yaml"
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


class Service(Supervised):
    def __init__(self, root=ROOT, state=None):
        rt = manifest(root).get("runtime") or "python"
        super().__init__(root, ENTRY[rt] + ["--port", "{port}", "--db", "{state}/booking.db"], ready="/resources", state=state, limits=LIMITS[rt])
        self.runtime = rt
    def __repr__(self): return "<service>"      # a failing test's output shows its fixtures: not the harness's module path (gate/packet.py distills what an agent reads)
    def start(self, timeout=20.0):
        super().start(timeout); self.client = Client(self.url()); return self


class Interleaved(Service):
    """The same service under the controller of gate/interleave.py (Python runtime only; docs/rfc/0007 § 6): requests are held at
    their first line in service/ and released in the order a schedule says, so a race is explored, not hoped for. `control` is the
    directory the judge and the controller exchange episodes through; the judge creates it and hands it to the candidate's identity,
    as the supervisor does for the state directory. SQLite is the Python runtime's store, so its module is the one the controller
    models (--dbapi); the lock of a store that has no database is a threading lock, which the controller replaces anyway."""
    def __init__(self, root=ROOT, state=None):
        super().__init__(root, state)
        assert self.runtime == "python", "the controller drives Python services"
        self.control = self.state / "interleave"; self.control.mkdir(parents=True, exist_ok=True)
        ident = SB.candidate_identity()
        if ident: os.chown(self.control, *ident)
        self.argv = [sys.executable, "-I", "gate/interleave.py", "serve", "--control", str(self.control), "--root", "service", "--dbapi", "sqlite3",
                     "--", "service/run.py", "--port", "{port}", "--db", "{state}/booking.db"]
