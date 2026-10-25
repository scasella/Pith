"""runtime/stack.py — the driver's library for the booking-quota composition (composition policy, run by the judge; the
candidate never sees it). It starts every process of the composition through gate/service.py (the candidate's identity,
a scrubbed environment, its own state directory), each behind its OWN judge-owned fault proxy, and reads the shared
invariants only from the components' own state through the judge's HTTP client (booking's listing, quota's grants,
the coordinator's stored receipts), never from anything the coordinator reports about itself.

PITH_COMPOSE_WORKSPACE is the judged workspace root (the evaluator, this composition's policy, the support files and a
copy of the candidate's artifact)."""
import json, os, pathlib, re, shutil, sys, tempfile, time, urllib.error, urllib.request
import yaml

WS = pathlib.Path(os.environ["PITH_COMPOSE_WORKSPACE"]).resolve()
sys.path.insert(0, str(WS)); sys.path.insert(0, str(WS / "obligations" / "app"))
from gate.service import Supervised          # noqa: E402
from gate import sandbox as SB                # noqa: E402
from faultproxy import FaultProxy            # noqa: E402

SPEC = yaml.safe_load((WS / "composition" / "composition.yaml").read_text())["runtime"]
COMPONENTS = {c["id"]: c for c in SPEC["components"]}
ORDER = ("booking", "quota", "coordinator")         # the coordinator is started last: it is given the other two's proxies
NOW = 100                                            # every reservation names the same instant: the quota's clock never moves backwards
RECOVERY_TIMEOUT = 12.0                              # a bound on waiting for recovery, never the oracle: the oracle is the components' state


class Http:
    """The judge's own client. Every method returns (status, parsed body); a connection that breaks raises."""
    def __init__(self, base): self.base = base

    def _req(self, method, path, body=None, timeout=15):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: code, raw = r.status, r.read()
        except urllib.error.HTTPError as e: code, raw = e.code, e.read()
        try: return code, json.loads(raw) if raw else None
        except ValueError: return code, None

    def get(self, path): return self._req("GET", path)
    def post(self, path, body): return self._req("POST", path, body)


def lost(fn, *a, **kw):
    """Run a client call whose answer is expected to be lost; returns its answer, or None when the connection broke."""
    try: return fn(*a, **kw)
    except Exception: return None


def wait_for(cond, timeout=RECOVERY_TIMEOUT, step=0.05):
    """Poll `cond` until it holds or the bound passes; returns whether it held. Used to wait on the components' state."""
    t0 = time.monotonic()
    while True:
        if cond(): return True
        if time.monotonic() - t0 > timeout: return False
        time.sleep(step)


class Stack:
    def __init__(self, root):
        self.root = pathlib.Path(root); self.svc = {}; self.proxy = {}

    # ---- processes ----
    def start(self):
        for cid in ORDER: self.up(cid)
        return self

    def up(self, cid):
        c = COMPONENTS[cid]; state = self.root / cid; state.mkdir(parents=True, exist_ok=True)
        argv = [re.sub(r"\{url:(\w+)\}", lambda m: self.proxy[m[1]].base, a.replace("{python}", sys.executable)) for a in c["argv"]]
        s = Supervised(WS, argv, ready=c.get("ready", "/health"), state=state); s.start()
        if cid in self.proxy: self.proxy[cid].upstream = s.url()           # a restarted process has a new port; its proxy (and so its clients) keep the old address
        else: self.proxy[cid] = FaultProxy(s.url()).start()
        self.svc[cid] = s
        if cid == "booking": self.booking = Http(s.url())                    # the judge's own view of each component: directly, never through a fault
        if cid == "quota": self.quota = Http(s.url())
        if cid == "coordinator": self.coord = Http(self.proxy[cid].base)    # the client's view of the coordinator: through its proxy
        return s

    def kill(self, cid): self.svc[cid].kill()

    def restart(self, cid): self.svc[cid].kill(); return self.up(cid)

    def stop(self):
        for s in self.svc.values(): s.stop()
        for p in self.proxy.values(): p.stop()

    # ---- the client ----
    def resource(self, rid):
        code, b = self.booking.post("/resources", {"id": rid, "name": f"room {rid}"}); assert code == 201, (code, b)

    def reserve(self, rq, resource, start, end, client=None):
        return (client or self.coord).post("/reservations", {"request_id": rq, "resource": resource, "start": start, "end": end, "now": NOW})

    # ---- what the components themselves say ----
    def active(self, resource):
        """The ids of the resource's active bookings, from the booking component's own listing."""
        code, b = self.booking.get(f"/resources/{resource}"); assert code == 200, (code, b)
        return {x["id"] for x in b["bookings"] if x["active"]}

    def grants(self, resource):
        """The request ids the quota component has granted a unit for the resource, from its own listing."""
        code, b = self.quota.get(f"/grants?key=resource:{resource}"); assert code == 200, (code, b)
        return b["grants"]

    def at_rest(self, resource): return self.active(resource) == set(self.grants(resource))

    def wait_rest(self, resource, timeout=RECOVERY_TIMEOUT):
        """Wait, with no client retry, for the resource's active bookings and quota grants to name the same requests."""
        return wait_for(lambda: self.at_rest(resource), timeout)

    def booking_is_active(self, rq):
        """True / False for an active / cancelled booking, None when booking has no such booking."""
        code, b = self.booking.get(f"/bookings/{rq}")
        return b["active"] if code == 200 else None

    def receipt_problem(self, rq, resource):
        """Why the coordinator's stored receipt for `rq` disagrees with the components' own state (None: it agrees)."""
        code, rc = self.coord.get(f"/reservations/{rq}")
        if code != 200: return f"the coordinator has no receipt for {rq} ({code})"
        active, granted, o = self.booking_is_active(rq), rq in self.grants(resource), rc["outcome"]
        if o == "ACCEPTED": ok = active is True and granted
        elif o == "QUOTA_EXCEEDED": ok = active is False and not granted      # compensated: booked, then cancelled, and no unit
        else: ok = active is None and not granted                             # CONFLICT, INVALID: nothing was booked, nothing was granted
        return None if ok else f"receipt for {rq} says {o}, but its booking active={active} and its unit granted={granted}"


def fresh_state():
    return pathlib.Path(tempfile.mkdtemp(prefix="composed-state-"))


def acquires_reaching_quota(stack, rq):
    """How many acquire calls for request `rq` reached the quota component's proxy (the judge's own log)."""
    n = 0
    for r in stack.proxy["quota"].requests("POST"):
        if r["path"] == "/acquire" and json.loads(r["body"] or "{}").get("request_id") == rq: n += 1
    return n
