"""A sliding-window quota limiter: a per-key log of grants, pruned as they expire.

    from limiter import Limiter
    lim = Limiter(limit=3, window=60)
    d = lim.acquire("alice", now=10)          # Decision(granted=True, remaining=2, retry_after=None)

Time is whatever the caller says it is (`now`), so the limiter is deterministic and testable. One Limiter may be
shared by threads.
"""
import json, re, threading
from collections import deque
from dataclasses import dataclass
from typing import Optional

__all__ = ["Limiter", "Decision", "LimiterError", "InvalidArgument", "ClockRegression"]

_MAX31, _MAX53 = 2 ** 31 - 1, 2 ** 53 - 1
_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class LimiterError(Exception):
    """Base class of everything this library raises on purpose."""


class InvalidArgument(LimiterError, ValueError):
    def __init__(self, argument, detail):
        super().__init__(f"{argument}: {detail}")
        self.argument = argument


class ClockRegression(LimiterError):
    def __init__(self, now, clock):
        super().__init__(f"now={now} is earlier than the limiter's clock ({clock}); time only moves forward")
        self.now, self.clock = now, clock


@dataclass(frozen=True)
class Decision:
    granted: bool
    remaining: int
    retry_after: Optional[int]


def _whole(name, v, lo, hi):
    if type(v) is not int or not lo <= v <= hi:
        raise InvalidArgument(name, f"must be a whole number in [{lo}, {hi}], got {v!r}")
    return v


def _key(k):
    if not isinstance(k, str) or not _KEY.fullmatch(k):
        raise InvalidArgument("key", f"must be 1-64 characters of A-Z a-z 0-9 _ . : -, got {k!r}")
    return k


class Limiter:
    def __init__(self, *, limit, window):
        self.limit = _whole("limit", limit, 1, _MAX31)
        self.window = _whole("window", window, 1, _MAX31)
        self._clock = 0
        self._log = {}                       # key -> deque[(t, cost)], oldest first, only grants that may still count
        self._lock = threading.Lock()
        self._history = []                   # DEFECT: every grant ever made, carried in every dump

    # -- internals (call with the lock held) --
    def _advance(self, now):
        if now < self._clock: raise ClockRegression(now, self._clock)
        self._clock = now

    def _live(self, key, now):
        q = self._log.get(key)
        if q is None: return deque(), 0
        while q and q[0][0] + self.window <= now: q.popleft()      # a grant at t stops counting at t + window
        if not q: del self._log[key]; return deque(), 0
        return q, sum(c for _, c in q)

    def _retry_after(self, q, used, cost, now):
        if cost > self.limit: return None
        need = used + cost - self.limit                             # how much must expire first
        for t, c in q:
            need -= c
            if need <= 0: return t + self.window - now
        raise AssertionError("unreachable: everything expires within one window")

    # -- the API --
    def acquire(self, key, *, now, cost=1):
        key = _key(key); cost = _whole("cost", cost, 1, _MAX31); now = _whole("now", now, 0, _MAX53)
        with self._lock:
            self._advance(now)
            q, used = self._live(key, now)
            if used + cost <= self.limit:
                self._log.setdefault(key, q).append((now, cost)); self._history.append([key, now, cost])
                return Decision(True, self.limit - used - cost, None)
            return Decision(False, self.limit - used, self._retry_after(q, used, cost, now))

    def peek(self, key, *, now):
        key = _key(key); now = _whole("now", now, 0, _MAX53)
        with self._lock:
            self._advance(now)
            return self.limit - self._live(key, now)[1]

    def dump(self):
        with self._lock:
            log = {}
            for k in list(self._log):
                q, _ = self._live(k, self._clock)
                if q: log[k] = [list(e) for e in q]
            return json.dumps({"format": "sliding-log/1", "limit": self.limit, "window": self.window, "clock": self._clock, "log": log, "history": self._history},
                              sort_keys=True, separators=(",", ":"))

    @classmethod
    def load(cls, text):
        try:
            d = json.loads(text) if isinstance(text, str) else None
            assert isinstance(d, dict) and d.get("format") == "sliding-log/1"
            lim = cls(limit=d["limit"], window=d["window"])
            lim._clock = _whole("clock", d["clock"], 0, _MAX53)
            assert isinstance(d["log"], dict)
            for k, entries in d["log"].items():
                _key(k); prev = -1; q = deque()
                for t, c in entries:
                    _whole("t", t, 0, lim._clock); _whole("c", c, 1, _MAX31)
                    assert prev <= t and t + lim.window > lim._clock; prev = t
                    q.append((t, c))
                assert q and sum(c for _, c in q) <= lim.limit
                lim._log[k] = q
            return lim
        except (AssertionError, LimiterError, KeyError, TypeError, ValueError) as e:
            raise InvalidArgument("text", "not a dump produced by Limiter.dump()") from e
