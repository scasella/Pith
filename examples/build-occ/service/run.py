"""service/run.py — the entrypoint the judge starts as a separate process (see AGENT.md)."""
import argparse, pathlib, sys, threading, signal
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from service.app import serve
from profiles.sqlite_occ.repo import Repo

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
    repo = Repo(a.db); srv = serve(repo, a.port)
    stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"auth-service on http://127.0.0.1:{a.port}", flush=True)
    stop.wait(); srv.shutdown()

if __name__ == "__main__":
    main()
