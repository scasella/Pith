"""coordinator/run.py — the coordinator: python -I coordinator/run.py --port P --state DIR --component booking=URL --component quota=URL
(runtime/RUNTIME.md). Serves 127.0.0.1:P, keeps its saga log and receipts in DIR/coordinator.db, exits on SIGTERM. On start, and
every quarter second after, it finishes or compensates every saga in its log: a crashed coordinator needs no client retry."""
import argparse, pathlib, signal, sys, threading
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                    # -I does not put this directory on sys.path
from app import serve
from peers import Peer
from saga import Coordinator, Log


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--state", required=True)
    ap.add_argument("--component", action="append", default=[], metavar="NAME=URL"); a = ap.parse_args()
    urls = dict(c.split("=", 1) for c in a.component)
    if set(urls) != {"booking", "quota"}: sys.exit("--component booking=URL and --component quota=URL are required")
    coord = Coordinator(Log(str(pathlib.Path(a.state) / "coordinator.db")), Peer(urls["booking"]), Peer(urls["quota"]))
    stop = threading.Event()

    def recover():
        while not stop.is_set():
            try: coord.recover_all()
            except Exception as e: print(f"recovery: {e}", flush=True)
            stop.wait(0.25)
    srv = serve(coord, a.port); threading.Thread(target=recover, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"coordinator on http://127.0.0.1:{a.port}", flush=True)
    stop.wait(); srv.shutdown()


if __name__ == "__main__":
    main()
