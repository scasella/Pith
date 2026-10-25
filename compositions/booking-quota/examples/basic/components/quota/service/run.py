"""service/run.py — the quota component: python -I service/run.py --port P --db PATH [--limit N] [--window W]
(runtime/RUNTIME.md). Serves 127.0.0.1:P, keeps its state in the SQLite file PATH, exits on SIGTERM."""
import argparse, pathlib, signal, sys, threading
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "lib"))        # -I does not put either on sys.path
from service.app import serve
from service.ledger import Ledger


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True)
    ap.add_argument("--limit", type=int, default=1); ap.add_argument("--window", type=int, default=1000000); a = ap.parse_args()
    srv = serve(Ledger(a.db, a.limit, a.window), a.port)
    stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"quota on http://127.0.0.1:{a.port}", flush=True)
    stop.wait(); srv.shutdown()


if __name__ == "__main__":
    main()
