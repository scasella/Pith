"""service/run.py — python -I service/run.py --port P --db PATH (harness/SERVICE.md)."""
import argparse, pathlib, signal, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from service.app import serve
from service.store import Store

ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
srv = serve(Store(a.db), a.port); stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set())
print(f"policy approvals on http://127.0.0.1:{a.port}", flush=True); stop.wait(); srv.shutdown()
