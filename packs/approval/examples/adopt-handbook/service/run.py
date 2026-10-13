"""service/run.py — python -I service/run.py --port P --db PATH. Added for the Pith adoption: exposes the handbook's
review workflow (handbook/reviews.py) through the pith.approval service contract (harness/SERVICE.md). It holds no
rules of its own; it maps HTTP onto Reviews and Reviews' errors onto status codes."""
import argparse, pathlib, signal, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from handbook.db import Database
from handbook.reviews import Reviews
from service.api import serve

ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
srv = serve(Reviews(Database(a.db)), a.port); stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set())
print(f"handbook reviews on http://127.0.0.1:{a.port}", flush=True); stop.wait(); srv.shutdown()
