"""service/run.py — the entrypoint the judge starts (harness/SERVICE.md): python -I service/run.py --port P --db PATH."""
import argparse, pathlib, signal, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from service.app import serve
from service.store import Store


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
    srv = serve(Store(a.db), a.port)
    stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"room calendar on http://127.0.0.1:{a.port}", flush=True)
    stop.wait(); srv.shutdown()


if __name__ == "__main__":
    main()
