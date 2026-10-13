"""harness/supervisor.py — how this pack starts the candidate's service. FROZEN.

The entrypoint follows app.manifest.yaml:runtime (harness/SERVICE.md); starting, the state directory, the candidate's
identity and limits, crash and restart are the evaluator's (gate/service.py). The harness never imports candidate code.
"""
import pathlib, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate.service import Supervised
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
    def start(self, timeout=20.0):
        super().start(timeout); self.client = Client(self.url()); return self
