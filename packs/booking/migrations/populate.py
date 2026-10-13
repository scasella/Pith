"""migrations/populate.py — produce real interval-booking-core/v1 state by driving the OLD judged artifact's own service.
FROZEN. Run by gate/migrate.py in the new release's workspace:

    populate.py --old OLD_WORKSPACE --state DIR --out observed.json

The old service is started the way the old harness's supervisor starts it (harness/supervisor.py: the runtime named by
the OLD artifact's app.manifest.yaml, python or node, on DIR/booking.db, as the candidate). It exercises every write
version 1 has: resources, accepted bookings (two of them touching, which buffer 0 must keep valid), a conflict, an
invalid interval, a cancellation and a refused one, an accepted and a refused reschedule, a move of a cancelled
booking, and a request in flight when the service is SIGKILLed. What the old service acknowledged (every result, the
resources, calendars and bookings it served, its event history, the request in flight) is written to observed.json,
which migrations/verify.py holds the new service to."""
import argparse, json, pathlib, sys, threading, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service

ap = argparse.ArgumentParser(); ap.add_argument("--old", required=True); ap.add_argument("--state", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()

old = Service(a.old, state=a.state).start(); c = old.client
results = {}                                           # request_id -> {op, args, result}: what the old service acknowledged


def write(op, *args):
    """One acknowledged write: op is book (resource, request_id, start, end), cancel (booking, request_id) or move
    (booking, request_id, start, end); the request id is args[1]."""
    code, body = getattr(c, op)(*args)
    assert code == 200 and body["replayed"] is False, (op, args, code, body)
    results[str(args[1])] = {"op": op, "args": list(args), "result": body}
    return body


assert c.create(1, "Room A")[0] == 201 and c.create(2, "Room B")[0] == 201
write("book", 1, 101, 600, 660)                        # accepted
write("book", 1, 102, 660, 720)                        # accepted: starts exactly when 101 ends (free at buffer 0)
write("book", 1, 103, 540, 600)                        # accepted: ends exactly when 101 starts
write("book", 1, 104, 630, 690)                        # conflict
write("book", 1, 105, 700, 700)                        # invalid
write("book", 2, 106, 600, 660)                        # accepted, then cancelled
write("cancel", 106, 107)                              # cancelled
write("cancel", 106, 108)                              # refused: already cancelled
write("move", 101, 109, 610, 660)                      # accepted reschedule (within its own time, still touching 102)
write("move", 102, 110, 600, 700)                      # refused reschedule (conflict): 102 stays where it was
write("move", 106, 111, 700, 760)                      # refused: not active
write("book", 2, 112, 800, 860)                        # accepted

# a request in flight when the old service dies: sent, then SIGKILL before (or while) it answers
IN_FLIGHT = {"op": "book", "args": [2, 113, 700, 760]}
def _try():
    try: c.book(*IN_FLIGHT["args"])
    except Exception: pass
t = threading.Thread(target=_try, daemon=True); t.start(); time.sleep(0.01); old.kill(); t.join(5)
c = old.start().client
assert c.book(1, 101, 600, 660)[1]["replayed"] is True             # the restarted old service still has what it acknowledged
write("book", 2, 114, 900, 960)                                    # accepted after the restart

res = c.resources()[1]["resources"]
views = {str(r["id"]): c.resource(r["id"])[1] for r in res}
ids = sorted({b["id"] for v in views.values() for b in v["bookings"]})
obs = {"format": "pith.migration-observed/v1", "runtime": old.runtime, "resources": res, "views": views,
       "bookings": {str(i): c.booking(i)[1] for i in ids}, "results": results, "in_flight": [IN_FLIGHT], "events": c.events()[1]}
old.stop()
outcomes = [r["result"].get("outcome") for r in results.values()]
assert {"ACCEPTED", "CONFLICT", "INVALID", "NOT_ACTIVE"} <= set(outcomes), outcomes                       # every kind of decision
assert {r["result"].get("cancelled") for r in results.values() if r["op"] == "cancel"} == {True, False}    # a cancel and a refused one
assert obs["bookings"]["102"]["start"] == obs["bookings"]["101"]["end"] == 660 and obs["bookings"]["106"]["active"] is False, obs["bookings"]
pathlib.Path(a.out).write_text(json.dumps(obs, indent=1)); print(json.dumps({k: obs[k] for k in ("runtime", "resources", "in_flight")}))
