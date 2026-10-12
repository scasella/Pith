"""Loads the translated proven core and defines the runtime DOMAIN the proof assumes.

The compiled Python does not check preconditions or `nat` domains. Everything that reaches the
core must come through `validate_*` here (or an equivalent in a custom profile that passes
obligations/adapter/harness.py). Domain profile (see INTENT.md):
  - amounts and limits are integers in [1, 2**53) for amounts, [0, 2**53) for limits/posted
  - request and account ids are integers in [0, 2**53)
  - bools are rejected even though they subclass int
  - zero amounts are rejected at the boundary: they are not a decision (no event), they are an invalid request
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "kernel" / "core" / "py" / "authcore-py"))
import _dafny, module_, AuthSpec, AuthCore, PostingCore   # noqa: E402,F401  (module_ fixes the translator's import order)

MAX = 2 ** 53

class InvalidRequest(ValueError): pass
class DuplicateAccount(ValueError): pass
class ConflictingReplay(ValueError): pass
class UnknownAccount(KeyError): pass

def _int(x, name, lo):
    if isinstance(x, bool) or not isinstance(x, int) or x < lo or x >= MAX:
        raise InvalidRequest(f"{name} must be an integer in [{lo}, 2^53), got {x!r}")
    return x
def validate_amount(x): return _int(x, "amount", 1)
def validate_limit(x):  return _int(x, "limit", 0)
def validate_id(x, name="id"): return _int(x, name, 0)

Account = AuthSpec.Account_Account
Request = AuthSpec.Request_Request
Auth, Decl, Rel, Post = AuthSpec.Status_Auth(), AuthSpec.Status_Decl(), AuthSpec.Status_Rel(), AuthSpec.Status_Post()
STATUS_NAME = {Auth: "AUTH", Decl: "DECL", Rel: "REL", Post: "POST"}       # wire names = constructor names upper-cased (gen/generate.py uses the same rule)
NAME_STATUS = {v: k for k, v in STATUS_NAME.items()}
Core = AuthCore.Core
Poster = PostingCore.Poster

def fresh_account(limit): return Account(limit, 0, _dafny.Map({}), _dafny.Map({}))
def available(a): return int(a.limit) - int(a.posted) - sum(int(v) for _, v in a.holds.items)   # .items: .values is a Set
def holds(a):  return {int(k): int(v) for k, v in a.holds.items}
def status(a): return {int(k): STATUS_NAME[v] for k, v in a.status.items}
