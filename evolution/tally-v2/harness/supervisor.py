"""harness/supervisor.py — how this pack starts the candidate's service. FROZEN once sealed. Starting, identity, limits,
crash and restart are the evaluator's (gate/service.py); the harness never imports candidate code."""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate.service import Supervised
from harness.client import Client


class Service(Supervised):
    def __init__(self, root=ROOT, state=None):
        super().__init__(root, [sys.executable, "-I", "service/run.py", "--port", "{port}", "--db", "{state}/tally.db"], ready="/tally", state=state)
    def start(self, timeout=20.0):
        super().start(timeout); self.client = Client(self.url()); return self
