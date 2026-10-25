#!/usr/bin/env python3
"""
gate/interleave.py — deterministic interleavings of concurrent code under test. FROZEN. Domain-free.

The threads under test run ONE AT A TIME and switch only at schedule points: acquiring or releasing a lock, a sleep,
each statement on a connection of a DB-API module the pack names (`dbapi`), and (for code under declared roots) each
line. Locks, sleeps and those connections are replaced with cooperative versions before the code under test is imported
(install()), and the database's write lock is modelled (taken by a connection's first write statement or a BEGIN
IMMEDIATE/EXCLUSIVE, released when the connection leaves its transaction, `in_transaction` false), so a correct store
never blocks where the controller cannot see it. A thread that the controller has not registered runs exactly as before.

Exploration is systematic and preemption-bounded (Musuvathi and Qadeer, iterative context bounding): every schedule
that switches away from a runnable thread at most `bound` times. The set of schedules is a function of the code and the
test, so a defect reachable within the bound is found on every run, with no sleeps and no timing. A thread that blocks
outside the controller's view (a C extension waiting on something the controller does not model) trips a watchdog and
the schedule is reported `inconclusive`, never as a pass.

In-process (a pack's profile tests, a library driver that already runs the candidate's code as the candidate):

    import interleave as IL; IL.install(roots=[...])           # before importing the code under test
    rep = IL.explore(setup, [f, g], check, bound=2)            # rep["violations"], rep["schedules"], rep["complete"]

A service (Python only), started by a pack harness through gate/service.py as the candidate:

    python3 -I gate/interleave.py serve --control DIR [--root R ...] [--dbapi MODULE ...] -- SCRIPT [ARGS ...]
    and in the harness: IL.ServiceEpisodes(DIR) drives episodes (see its docstring)

Added in v0.13.0 (docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 6).
"""
import _thread, json, os, pathlib, re, sys, threading, time

_real_sleep = time.sleep
_RealLock = _thread.allocate_lock
_RealThreadingLock, _RealThreadingRLock = threading.Lock, threading.RLock
_SELF = os.path.realpath(__file__)
_inside = threading.local()            # a schedule point never re-enters the controller
WATCHDOG = float(os.environ.get("PITH_INTERLEAVE_WATCHDOG", "5"))


class Deadlock(Exception): pass
class Inconclusive(Exception): pass


class Controller:
    """Runs registered threads one at a time. `forced` is a list of thread indices: at the k-th decision point with
    more than one runnable thread, run forced[k]; past it, keep running the current thread if it is runnable, else the
    lowest-numbered runnable one. Every decision point is recorded, so an explorer can derive the next schedules."""

    def __init__(self, nthreads, forced=(), roots=()):
        self.n = nthreads; self.forced = list(forced); self.roots = tuple(str(r) for r in roots)
        self.mu = _RealLock(); self.cv = threading.Condition(_RealLock())
        self.registered = {}                      # thread ident -> index
        self.blocked = {}                         # index -> object it waits for
        self.done = set(); self.current = None; self.decisions = []; self.points = 0
        self.state = "arming"                     # arming -> running -> finished | inconclusive | deadlock
        self.last_progress = time.monotonic(); self.error = None

    # -- registration --
    def register(self, idx=None):
        me = threading.get_ident()
        with self.cv:
            if me in self.registered: return self.registered[me]
            idx = len(self.registered) if idx is None else idx
            self.registered[me] = idx; self.cv.notify_all()
            return idx

    def index(self):
        return self.registered.get(threading.get_ident())

    def start(self):
        """All threads registered and parked at their first point: begin with thread 0."""
        with self.cv:
            self.state = "running"; self.current = self._choose(initial=True); self.last_progress = time.monotonic(); self.cv.notify_all()

    # -- scheduling --
    def runnable(self):
        return [i for i in range(self.n) if i not in self.done and i not in self.blocked]

    def _choose(self, initial=False):
        r = self.runnable()
        if not r:
            if len(self.done) < self.n: self.state = "deadlock"; self.error = f"every unfinished thread is blocked: {self.blocked}"
            else: self.state = "finished"
            return None
        if len(r) == 1 and not initial and self.current in r: return self.current
        if len(r) > 1 or initial:
            k = len(self.decisions)
            if k < len(self.forced) and self.forced[k] in r: pick = self.forced[k]
            elif self.current in r: pick = self.current
            else: pick = r[0]
            self.decisions.append({"runnable": r, "current": self.current, "chose": pick})
            return pick
        return r[0]

    def point(self, kind="point", blocked_on=None):
        """Called by a registered thread at a schedule point. Returns when it is this thread's turn again."""
        me = self.index()
        if me is None or self.state not in ("running",) or getattr(_inside, "on", False): return
        _inside.on = True
        try:
            with self.cv:
                self.points += 1; self.last_progress = time.monotonic()
                if blocked_on is not None: self.blocked[me] = blocked_on
                nxt = self._choose()
                self.current = nxt; self.cv.notify_all()
                self._wait_turn(me)
        finally:
            _inside.on = False

    def _wait_turn(self, me):
        while self.state == "running" and self.current != me:
            self.cv.wait(0.05)
            if self.state == "running" and time.monotonic() - self.last_progress > WATCHDOG:
                self.state = "inconclusive"; self.error = f"no schedule point for {WATCHDOG}s: thread {self.current} is blocked outside the controller's view"
                self.cv.notify_all()

    def unblock(self, obj):
        with self.cv:
            for i, o in list(self.blocked.items()):
                if o is obj: del self.blocked[i]

    def finish(self):
        me = self.index()
        if me is None: return
        with self.cv:
            self.done.add(me); self.blocked.pop(me, None); self.last_progress = time.monotonic()
            if self.state == "running": self.current = self._choose(); self.cv.notify_all()

    def wait_first_turn(self):
        """A newly registered thread parks here until the controller runs it."""
        me = self.index()
        with self.cv:
            while self.state == "arming": self.cv.wait(0.05)
            self._wait_turn(me)


ACTIVE = None   # the controller of the current episode (one at a time)


def _ctl():
    c = ACTIVE
    return c if (c is not None and c.state == "running" and c.index() is not None) else None


# ---------------------------------------------------------------- cooperative primitives
class CoopLock:
    """threading.Lock for code under test: a registered thread that finds it held yields to the controller (blocked on
    it) instead of blocking the process; anyone else uses the real lock."""
    def __init__(self): self._l = _RealLock(); self._owner = None

    def acquire(self, blocking=True, timeout=-1):
        c = _ctl()
        if c is None: return self._l.acquire(blocking, timeout)
        c.point("acquire")
        while not self._l.acquire(False):
            if not blocking: return False
            c.point("blocked", blocked_on=self)
        self._owner = threading.get_ident(); return True

    def release(self):
        self._owner = None; self._l.release()
        if ACTIVE is not None: ACTIVE.unblock(self)
        c = _ctl()
        if c is not None: c.point("release")

    def locked(self): return self._l.locked()
    __enter__ = lambda self: self.acquire()
    def __exit__(self, *a): self.release()
    def _at_fork_reinit(self): self._l = _RealLock()


class CoopRLock:
    def __init__(self): self._l = CoopLock(); self._owner = None; self._count = 0

    def acquire(self, blocking=True, timeout=-1):
        me = threading.get_ident()
        if self._owner == me: self._count += 1; return True
        if not self._l.acquire(blocking, timeout): return False
        self._owner, self._count = me, 1; return True

    def release(self):
        if self._owner != threading.get_ident(): raise RuntimeError("cannot release un-acquired lock")
        self._count -= 1
        if self._count == 0: self._owner = None; self._l.release()

    __enter__ = lambda self: self.acquire()
    def __exit__(self, *a): self.release()
    def _is_owned(self): return self._owner == threading.get_ident()


def coop_sleep(s):
    c = _ctl()
    if c is None: return _real_sleep(s)
    c.point("sleep")


# ---------------------------------------------------------------- a DB-API database, with its write lock modelled
_WRITE = re.compile(r"^\s*(BEGIN\s+(IMMEDIATE|EXCLUSIVE)|INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM)\b", re.I)
_db_locks = {}


class _DbLock:
    """The database file's write lock, held by one connection at a time."""
    def __init__(self): self.holder = None


def _db_lock(path):
    key = os.path.realpath(path) if path and path != ":memory:" else f"memory-{id(path)}"
    return _db_locks.setdefault(key, _DbLock())


class CoopConnection:
    def __init__(self, real, path): self._c = real; self._lock = _db_lock(path)

    def _before(self, sql):
        c = _ctl()
        if c is None: return
        c.point("sql")
        if _WRITE.match(sql or "") and self._lock.holder is not self:
            while self._lock.holder is not None and self._lock.holder is not self:
                c.point("blocked", blocked_on=self._lock)
            self._lock.holder = self

    def _after(self):
        if self._lock.holder is self and not self._c.in_transaction:
            self._lock.holder = None
            if ACTIVE is not None: ACTIVE.unblock(self._lock)

    def execute(self, sql, *a):
        self._before(sql)
        try: return self._c.execute(sql, *a)
        finally: self._after()

    def executemany(self, sql, *a):
        self._before(sql)
        try: return self._c.executemany(sql, *a)
        finally: self._after()

    def executescript(self, sql):
        self._before(sql)
        try: return self._c.executescript(sql)
        finally: self._after()

    def commit(self):
        c = _ctl()
        if c is not None: c.point("sql")
        try: return self._c.commit()
        finally: self._after()

    def rollback(self):
        try: return self._c.rollback()
        finally: self._after()

    def cursor(self, *a): return _CoopCursor(self, self._c.cursor(*a))
    def __enter__(self): return self
    def __exit__(self, t, v, tb):
        (self.commit() if t is None else self.rollback()); return False
    def __getattr__(self, k): return getattr(self._c, k)


class _CoopCursor:
    def __init__(self, conn, cur): self._conn = conn; self._cur = cur
    def execute(self, sql, *a):
        self._conn._before(sql)
        try: self._cur.execute(sql, *a); return self
        finally: self._conn._after()
    def executemany(self, sql, *a):
        self._conn._before(sql)
        try: self._cur.executemany(sql, *a); return self
        finally: self._conn._after()
    def __iter__(self): return iter(self._cur)
    def __getattr__(self, k): return getattr(self._cur, k)


# ---------------------------------------------------------------- install
_installed = {"roots": ()}


def install(roots=(), dbapi=()):
    """Replace threading.Lock/RLock, time.sleep and the `connect` of each DB-API module named in `dbapi` (the pack's
    harness names the module its stores use) with cooperative versions (idempotent). Call before the code under test is
    imported. `roots`: directories whose code gets a schedule point at every line."""
    import importlib
    _installed["roots"] = tuple(str(pathlib.Path(r).resolve()) for r in roots)
    for name in dbapi:
        if name in _installed.setdefault("dbapi", set()): continue
        mod = importlib.import_module(name); real = mod.connect
        def connect(database, *a, _real=real, **k):
            return CoopConnection(_real(database, *a, **k), database if isinstance(database, str) else str(database))
        mod.connect = connect; _installed["dbapi"].add(name)
    if _installed.get("done"): return
    threading.Lock = CoopLock; threading.RLock = CoopRLock; time.sleep = coop_sleep
    _installed["done"] = True


def uninstall():
    """Undo install() (for a test session that goes on with the standard library afterwards)."""
    import importlib
    if not _installed.get("done"): return
    threading.Lock = _RealThreadingLock; threading.RLock = _RealThreadingRLock; time.sleep = _real_sleep
    for name in _installed.get("dbapi", ()):
        mod = importlib.import_module(name)
        if hasattr(mod.connect, "__defaults__") and getattr(mod.connect, "__name__", "") == "connect" and mod.connect.__code__.co_filename == __file__:
            mod.connect = mod.connect.__kwdefaults__["_real"]
    _installed.clear(); _installed["roots"] = ()


def _tracer(frame, event, arg):
    roots = _installed["roots"]; f = frame.f_code.co_filename
    if not roots or not f.startswith(roots) or os.path.realpath(f) == _SELF: return None
    def local(frame, event, arg):
        if event == "line":
            c = _ctl()
            if c is not None: c.point("line")
        return local
    return local


# ---------------------------------------------------------------- in-process exploration
def run_once(setup, fns, forced, roots=()):
    """One schedule. Returns (controller, state, results)."""
    global ACTIVE
    state = setup(); c = Controller(len(fns), forced, roots); ACTIVE = c; results = [None] * len(fns)

    def body(i, f):                       # synchronised only through the controller's own (real) condition
        c.register(i); sys.settrace(_tracer)
        try:
            c.wait_first_turn()
            try: results[i] = ("ok", f(state))
            except BaseException as e: results[i] = ("error", f"{type(e).__name__}: {e}")
        finally:
            sys.settrace(None); c.finish()

    ts = [threading.Thread(target=body, args=(i, f), daemon=True) for i, f in enumerate(fns)]
    for t in ts: t.start()
    with c.cv:
        while len(c.registered) < len(fns): c.cv.wait(0.05)
    c.start()
    for t in ts: t.join(WATCHDOG * 4)
    if any(t.is_alive() for t in ts) and c.state == "running": c.state = "inconclusive"; c.error = "a thread did not finish"
    ACTIVE = None
    return c, state, results


def children(decisions, forced_len, bound):
    """Schedules one decision away from this run: at every decision point at or past the forced prefix, every other
    runnable thread, keeping at most `bound` preemptions (switching away from a runnable current thread)."""
    out = []
    pre = sum(1 for d in decisions[:forced_len] if d["current"] in d["runnable"] and d["chose"] != d["current"])
    for k in range(forced_len, len(decisions)):
        d = decisions[k]
        for alt in d["runnable"]:
            if alt == d["chose"]: continue
            p = pre + (1 if d["current"] in d["runnable"] and alt != d["current"] else 0)
            if p <= bound: out.append([x["chose"] for x in decisions[:k]] + [alt])
        if d["current"] in d["runnable"] and d["chose"] != d["current"]: pre += 1
    return out


def explore(setup, fns, check, bound=2, roots=(), max_schedules=5000, stop_at_first=False):
    """Every schedule of `fns` (each called with setup()'s state, in its own thread) with at most `bound` preemptions.
    check(state, results) returns None or a violation (a string). Deterministic: depth-first, lowest thread first."""
    todo = [[]]; seen = set(); rep = {"schedules": 0, "violations": [], "inconclusive": [], "deadlocks": [], "bound": bound, "complete": True}
    while todo:
        forced = todo.pop()
        if tuple(forced) in seen: continue
        seen.add(tuple(forced))
        if rep["schedules"] >= max_schedules: rep["complete"] = False; break
        c, state, results = run_once(setup, fns, forced, roots); rep["schedules"] += 1
        sched = [d["chose"] for d in c.decisions]
        if c.state == "inconclusive": rep["inconclusive"].append({"schedule": sched, "why": c.error}); continue
        if c.state == "deadlock": rep["deadlocks"].append({"schedule": sched, "why": c.error})
        v = check(state, results)
        if v: rep["violations"].append({"schedule": sched, "violation": v, "results": results})
        if v and stop_at_first: rep["complete"] = False; break
        todo.extend(reversed(children(c.decisions, len(forced), bound)))
    rep["first"] = rep["violations"][0] if rep["violations"] else None
    return rep


# ---------------------------------------------------------------- services (Python), driven episode by episode
# Protocol, through a control directory the judge creates and hands to the service (files written atomically):
#   judge    episode.json {"id", "threads", "forced"}     arm an episode
#   service  armed-<id>                                   armed; the next `threads` request threads that reach the
#   service  parked-<id>-<i>                              service's code register in arrival order and park
#   judge    go-<id>                                      every request issued and parked: run the schedule
#   service  result-<id>.json {"state", "decisions", ...} every registered thread finished (or a watchdog fired)
# The judge issues the requests one at a time, waiting for each to park, so arrival order is fixed.

def _write(p, obj):
    tmp = p.with_name(p.name + ".tmp"); tmp.write_text(json.dumps(obj)); os.replace(tmp, p)


def serve(argv):
    """python3 -I gate/interleave.py serve --control DIR [--root R ...] [--dbapi MODULE ...] [--lines] -- SCRIPT [ARGS ...]"""
    import runpy
    if "--" not in argv: sys.exit("usage: interleave.py serve --control DIR [--root R ...] [--dbapi MODULE ...] [--lines] -- SCRIPT [ARGS ...]")
    opts, rest = argv[:argv.index("--")], argv[argv.index("--") + 1:]
    ctl = pathlib.Path(opts[opts.index("--control") + 1]); roots = [opts[i + 1] for i, o in enumerate(opts) if o == "--root"]
    ctl.mkdir(parents=True, exist_ok=True)
    dbapi = [opts[i + 1] for i, o in enumerate(opts) if o == "--dbapi"]
    lines = "--lines" in opts
    script = pathlib.Path(rest[0]).resolve()
    install(roots or [script.parent], dbapi)
    main_ident = threading.get_ident(); roots_t = _installed["roots"]

    def reg_tracer(frame, event, arg):
        f = frame.f_code.co_filename
        if not roots_t or not f.startswith(roots_t) or os.path.realpath(f) == _SELF: return None
        c = ACTIVE
        if c is not None and c.state == "arming" and threading.get_ident() != main_ident and c.index() is None and len(c.registered) < c.n:
            i = c.register(); _write(ctl / f"parked-{c.episode}-{i}", {"thread": i}); c.wait_first_turn()
        if not lines: return None
        def local(frame, event, arg):
            if event == "line":
                cc = _ctl()
                if cc is not None: cc.point("line")
            return local
        return local
    threading.settrace(reg_tracer)

    run0 = threading.Thread.run
    def run(self):
        try: run0(self)
        finally:
            c = ACTIVE
            if c is not None and c.index() is not None: c.finish()
    threading.Thread.run = run

    def watcher():
        global ACTIVE
        seen = None
        while True:
            _real_sleep(0.01)
            ep = ctl / "episode.json"
            try: E = json.loads(ep.read_text()) if ep.exists() else None
            except ValueError: E = None
            if not E or E["id"] == seen: continue
            seen = E["id"]; c = Controller(int(E["threads"]), E.get("forced") or [], roots); c.episode = E["id"]; ACTIVE = c
            _write(ctl / f"armed-{E['id']}", {})
            while not (ctl / f"go-{E['id']}").exists():
                _real_sleep(0.005)
                if time.monotonic() - c.last_progress > WATCHDOG * 4: c.state = "inconclusive"; c.error = "the episode was never started"; break
            if c.state == "arming":
                if len(c.registered) < c.n: c.state = "inconclusive"; c.error = f"only {len(c.registered)} of {c.n} requests reached the service's code"
                else: c.start()
            while c.state == "running":
                _real_sleep(0.005)
                if time.monotonic() - c.last_progress > WATCHDOG * 2:
                    c.state = "inconclusive"; c.error = f"no schedule point for {WATCHDOG * 2}s: a thread is blocked outside the controller's view"
            with c.cv: c.cv.notify_all()
            _write(ctl / f"result-{E['id']}.json", {"state": c.state, "error": c.error, "decisions": c.decisions, "points": c.points})
            ACTIVE = None
    threading.Thread(target=watcher, daemon=True).start()
    sys.argv = [str(script)] + rest[1:]          # sys.path as `python -I SCRIPT` has it: the script's directory is NOT added (it would shadow the stdlib)
    runpy.run_path(str(script), run_name="__main__")


class ServiceEpisodes:
    """The judge's side: run schedules of concurrent requests against a service started through `serve`.

        E = ServiceEpisodes(control_dir)
        rep = E.explore(setup, [call_a, call_b], check, bound=1)
    setup() prepares fresh service state for one schedule (fresh ids) and returns a context; each call(ctx) issues ONE
    request; check(ctx, results) returns None or a violation. Same exploration as explore()."""

    def __init__(self, control, timeout=None):
        self.ctl = pathlib.Path(control); self.n = 0; self.timeout = timeout or WATCHDOG * 6

    def _wait(self, p):
        t0 = time.monotonic()
        while not p.exists():
            if time.monotonic() - t0 > self.timeout: raise Inconclusive(f"{p.name} did not appear within {self.timeout}s")
            _real_sleep(0.005)

    def run(self, forced, ctx, calls):
        self.n += 1; k = self.n; results = [None] * len(calls)
        _write(self.ctl / "episode.json", {"id": k, "threads": len(calls), "forced": list(forced)})
        self._wait(self.ctl / f"armed-{k}")
        ts = []
        for i, call in enumerate(calls):
            def go(i=i, call=call):
                try: results[i] = ("ok", call(ctx))
                except BaseException as e: results[i] = ("error", f"{type(e).__name__}: {e}")
            t = threading.Thread(target=go, daemon=True); t.start(); ts.append(t)
            self._wait(self.ctl / f"parked-{k}-{i}")
        (self.ctl / f"go-{k}").write_text("")
        self._wait(self.ctl / f"result-{k}.json")
        for t in ts: t.join(self.timeout)
        R = json.loads((self.ctl / f"result-{k}.json").read_text())
        return R, results

    def explore(self, setup, calls, check, bound=1, max_schedules=400, stop_at_first=False):
        todo = [[]]; seen = set(); rep = {"schedules": 0, "violations": [], "inconclusive": [], "deadlocks": [], "bound": bound, "complete": True}
        while todo:
            forced = todo.pop()
            if tuple(forced) in seen: continue
            seen.add(tuple(forced))
            if rep["schedules"] >= max_schedules: rep["complete"] = False; break
            ctx = setup()
            try: R, results = self.run(forced, ctx, calls)
            except Inconclusive as e: rep["inconclusive"].append({"forced_prefix": forced, "why": str(e)}); continue
            rep["schedules"] += 1; sched = [d["chose"] for d in R["decisions"]]
            if R["state"] == "inconclusive": rep["inconclusive"].append({"schedule": sched, "why": R["error"]}); continue
            if R["state"] == "deadlock": rep["deadlocks"].append({"schedule": sched, "why": R["error"]})
            v = check(ctx, results)
            if v: rep["violations"].append({"schedule": sched, "violation": v, "results": results})
            if v and stop_at_first: rep["complete"] = False; break
            todo.extend(reversed(children(R["decisions"], len(forced), bound)))
        rep["first"] = rep["violations"][0] if rep["violations"] else None
        return rep


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]: serve(sys.argv[2:])
    else: sys.exit(__doc__)
