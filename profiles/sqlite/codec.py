"""Account <-> JSON row. Obligation: decode(encode(a)) == a, canonical encoding, and decode VALIDATES
(a stored row outside the proof's domain is refused rather than handed to the core)."""
from . import core
import _dafny

def encode(a) -> dict:
    return {"limit": int(a.limit), "posted": int(a.posted),
            "holds":  sorted((int(k), int(v)) for k, v in a.holds.items),
            "status": sorted((int(k), core.STATUS_NAME[v]) for k, v in a.status.items)}

def decode(row: dict):
    limit, posted = core.validate_limit(row["limit"]), core.validate_limit(row["posted"])
    holds = {core.validate_id(k, "request_id"): core.validate_amount(v) for k, v in row["holds"]}
    status = {core.validate_id(k, "request_id"): core.NAME_STATUS[s] for k, s in row["status"]}
    # Valid(a): INV1, P2, P2'
    if posted + sum(holds.values()) > limit: raise core.InvalidRequest("stored state violates INV1")
    if set(holds) != {k for k, s in status.items() if s == core.Auth}: raise core.InvalidRequest("stored state violates P2")
    return core.Account(limit, posted, _dafny.Map(holds), _dafny.Map(status))
