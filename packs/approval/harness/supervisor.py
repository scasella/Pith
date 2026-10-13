"""harness/supervisor.py — how this pack starts the candidate's service and runs its CLI. FROZEN.
Entrypoints follow app.manifest.yaml:runtime (harness/SERVICE.md); starting, identity, limits, crash and restart are the
evaluator's (gate/service.py, gate/sandbox.py). The harness never imports candidate code."""
import pathlib, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate.service import Supervised
from gate import sandbox as SB
from harness.client import Client

SERVICE = {"python": [sys.executable, "-I", "service/run.py"], "node": ["node", "service/run.mjs"]}
CLI = {"python": [sys.executable, "-I", "cli/main.py"], "node": ["node", "cli/main.mjs"]}
LIMITS = {"python": {}, "node": {"RLIMIT_AS": None}}     # V8 reserves address space for WebAssembly (gate/sandbox.py limits)


def runtime(root=ROOT):
    p = pathlib.Path(root) / "app.manifest.yaml"
    return ((yaml.safe_load(p.read_text()) or {}) if p.exists() else {}).get("runtime") or "python"


class Service(Supervised):
    def __init__(self, root=ROOT, state=None):
        rt = runtime(root); self.runtime = rt
        super().__init__(root, SERVICE[rt] + ["--port", "{port}", "--db", "{state}/approval.db"], ready="/actors", state=state, limits=LIMITS[rt])
    def start(self, timeout=20.0):
        super().start(timeout); self.client = Client(self.url()); return self


def cli(args, root=ROOT, timeout=30):
    """Run the candidate's CLI once, under the candidate's identity and limits; returns (exit code, stdout, stderr)."""
    rt = runtime(root)
    return SB.run_as_candidate_full(CLI[rt] + list(args), cwd=root, timeout=timeout, limits=LIMITS[rt])
