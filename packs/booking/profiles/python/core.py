"""profiles/python/core.py — loads the translated verified core and defines the runtime domain the proof assumes. FROZEN.

The translated Python checks no preconditions and no `nat` domains. Everything that reaches the core comes through
validate_* here (a custom profile must establish the same, and is judged only through its service):
  - ids, starts and ends are integers in [0, 2**53); bools are rejected even though they subclass int
  - a booking id is new to its calendar when Book is called (the store checks the op log first)
  - a calendar is the slots of ONE resource, in booking-id order, as last committed
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "bookingcore-py"))
import _dafny, module_, BookingSpec, BookingCore   # noqa: E402,F401  (module_ first: the translator's import order)

MAX = 2 ** 53
WIRE = {"Accepted": "ACCEPTED", "Conflict": "CONFLICT", "Invalid": "INVALID", "NotActive": "NOT_ACTIVE"}   # wire name per outcome constructor


class InvalidRequest(ValueError): pass


def validate_int(x, name):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < MAX:
        raise InvalidRequest(f"{name} must be an integer in [0, 2^53), got {x!r}")
    return x


def calendar(rows):
    """rows: [(id, start, end, active)] in id order -> a Calendar value."""
    return _dafny.SeqWithoutIsStrInference([BookingSpec.Slot_Slot(i, s, e, bool(a)) for i, s, e, a in rows])


def rows(cal): return [(int(x.id_), int(x.start), int(x.end), bool(x.active)) for x in cal]


def outcome(o):
    """(wire name, conflicts_with) of an Outcome value."""
    name = type(o).__name__.split("_", 1)[1]
    return WIRE[name], (int(o.with_) if o.is_Conflict else None)


def valid(rs):
    """Valid(c) from the spec, on concrete rows: unique ids, well-formed intervals, no two active slots overlapping."""
    act = sorted((s, e) for _, s, e, a in rs if a)
    return len({i for i, *_ in rs}) == len(rs) and all(s < e for _, s, e, _ in rs) and all(act[k][1] <= act[k + 1][0] for k in range(len(act) - 1))


Core = BookingCore.Core
