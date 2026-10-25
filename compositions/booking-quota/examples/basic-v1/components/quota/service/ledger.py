"""service/ledger.py — the quota component's store: the pith.quota library's limiter (lib/limiter.py) made idempotent and
durable. Every acquire is recorded under its request id, and the limiter's dump is saved in the same SQLite transaction as
that record, so a restart (or a SIGKILL at any point) leaves either both or neither: it never grants a request twice and
never forgets a grant it answered. Stdlib only."""
import re, sqlite3, threading
from limiter import Limiter, InvalidArgument, ClockRegression

MAX53 = 2 ** 53
KEY = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class Mismatch(ValueError): pass


def whole(x, name):
    if type(x) is not int or not 0 <= x < MAX53: raise InvalidArgument(name, f"must be an integer in [0, 2^53), got {x!r}")
    return x


class Ledger:
    def __init__(self, path, limit, window):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False); self.lock = threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS limiter(id INTEGER PRIMARY KEY CHECK (id = 1), dump TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS acquires(request_id INTEGER PRIMARY KEY, key TEXT NOT NULL, now INTEGER NOT NULL, "
                        "granted INTEGER NOT NULL, remaining INTEGER NOT NULL, retry_after INTEGER)")
        row = self.db.execute("SELECT dump FROM limiter").fetchone()
        if row:                                        # the saved limiter is authoritative; the command line may not contradict it
            self.dump = row[0]; self.lim = Limiter.load(self.dump)
            if (self.lim.limit, self.lim.window) != (limit, window):
                raise SystemExit(f"state was made with limit={self.lim.limit} window={self.lim.window}, not {limit}/{window}")
        else:
            self.lim = Limiter(limit=limit, window=window); self.dump = self.lim.dump()
            self.db.execute("INSERT INTO limiter VALUES (1, ?)", (self.dump,))

    @staticmethod
    def _answer(request_id, key, now, granted, remaining, retry_after, replayed):
        return {"request_id": request_id, "key": key, "now": now, "granted": bool(granted), "remaining": remaining, "retry_after": retry_after, "replayed": replayed}

    def acquire(self, request_id, key, now):
        """One unit for `key` at instant `now`, decided once per request id. A repeat returns the recorded answer with
        replayed: true, whether it was granted or refused; reusing the id for another key or instant is a Mismatch.
        Raises InvalidArgument (a malformed key or instant) or ClockRegression (the limiter's clock is ahead); neither changes anything."""
        whole(request_id, "request_id"); whole(now, "now")
        if not isinstance(key, str) or not KEY.fullmatch(key): raise InvalidArgument("key", f"must match {KEY.pattern}")
        with self.lock:
            row = self.db.execute("SELECT key, now, granted, remaining, retry_after FROM acquires WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if (row[0], row[1]) != (key, now): raise Mismatch("request id reused for another key or instant")
                return self._answer(request_id, key, now, row[2], row[3], row[4], True)
            d = self.lim.acquire(key, now=now)
            dump = self.lim.dump()
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("INSERT INTO acquires VALUES (?, ?, ?, ?, ?, ?)", (request_id, key, now, int(d.granted), d.remaining, d.retry_after))
                self.db.execute("UPDATE limiter SET dump=? WHERE id=1", (dump,))
                self.db.execute("COMMIT")
            except sqlite3.Error:
                try: self.db.execute("ROLLBACK")
                except sqlite3.Error: pass
                self.lim = Limiter.load(self.dump)         # the in-memory limiter must not run ahead of what is saved
                raise
            self.dump = dump
            return self._answer(request_id, key, now, d.granted, d.remaining, d.retry_after, False)

    def grants(self, key):
        with self.lock: return [r[0] for r in self.db.execute("SELECT request_id FROM acquires WHERE key=? AND granted=1 ORDER BY request_id", (key,))]
