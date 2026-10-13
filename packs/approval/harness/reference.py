"""
harness/reference.py — the approval workflow as an executable reference model. FROZEN.

The pack's oracle is model/Approval.tla. This module is the same transition system written as a Python function, with
two additions the service contract needs and the model does not: revisions are unbounded, and a refused command says
WHY (harness/SERVICE.md § Refusals, in this precedence order). harness/refines.py checks, before any candidate is
judged, that within the model's bounds this module and the TLA+ spec have exactly the same reachable states and the
same labelled transitions; harness/conformance.py then holds the candidate's service to this module.

Each document carries its own quorum (A3, A9): chosen at create (QUORUMS, default 2), never changed by any command.
"""
from dataclasses import dataclass, field, replace

ROLES = ("editor", "approver", "publisher")
REASONS = ("ROLE", "STALE_REVISION", "WRONG_STATE", "NOT_AUTHOR", "SEPARATION_OF_DUTIES", "ALREADY_APPROVED")
QUORUMS = range(2, 6)                       # the service's domain for create's `quorum` (harness/SERVICE.md); outside it: 400
DEFAULT_QUORUM = 2                          # create without `quorum`; every version 1 document (migrations/from-v1.yaml)


@dataclass(frozen=True)
class Doc:
    status: str = "draft"                   # draft | in_review | approved | rejected | published
    rev: int = 1
    authors: tuple = ()                     # authors[r - 1] wrote revision r
    approvals: frozenset = field(default_factory=frozenset)    # {(revision, approver)}; old pairs are history
    quorum: int = DEFAULT_QUORUM            # distinct approvals of the current revision this document needs; fixed at create
    last: tuple = ()                        # (command, actor, revision) of the step that made this state: the model's history variable

    def votes(self, r): return {a for (q, a) in self.approvals if q == r}


def create(actor, roles, quorum=DEFAULT_QUORUM):
    """(reason or None, Doc or None). `quorum` is in the domain (the boundary refuses anything else with 400)."""
    if "editor" not in roles.get(actor, ()): return "ROLE", None
    return None, Doc(authors=(actor,), quorum=quorum, last=("create", actor, 1))


def step(d, op, actor, roles, revision=None, max_rev=None):
    """Apply one command to a document. Returns (reason, Doc): reason None means OK and Doc is the new state;
    otherwise Doc is unchanged. `revision` is the revision the command is about (every command but edit names one).
    No command changes d.quorum."""
    has = lambda role: role in roles.get(actor, ())
    if op == "edit":
        if not has("editor"): return "ROLE", d
        if d.status == "published" or (max_rev is not None and d.rev >= max_rev): return "WRONG_STATE", d
        return None, replace(d, rev=d.rev + 1, authors=d.authors + (actor,), status="draft", last=("edit", actor, d.rev + 1))
    need = {"submit": None, "approve": "approver", "reject": "approver", "publish": "publisher"}[op]
    if need and not has(need): return "ROLE", d
    if revision != d.rev: return "STALE_REVISION", d
    if d.status != {"submit": "draft", "approve": "in_review", "reject": "in_review", "publish": "approved"}[op]: return "WRONG_STATE", d
    done = lambda **kw: (None, replace(d, last=(op, actor, revision), **kw))
    if op == "submit":
        return done(status="in_review") if actor == d.authors[d.rev - 1] else ("NOT_AUTHOR", d)
    if op in ("approve", "reject") and actor == d.authors[d.rev - 1]: return "SEPARATION_OF_DUTIES", d
    if op == "approve":
        if (d.rev, actor) in d.approvals: return "ALREADY_APPROVED", d
        ap = d.approvals | {(d.rev, actor)}
        return done(approvals=ap, status="approved" if len({a for (q, a) in ap if q == d.rev}) >= d.quorum else "in_review")
    if op == "reject": return done(status="rejected")
    return done(status="published")


def view(d):
    """The document as the service reports it (harness/SERVICE.md GET /documents/{id}), minus title and bodies."""
    return {"status": d.status, "revision": d.rev, "authors": list(d.authors), "quorum": d.quorum,
            "approvals": sorted([{"revision": r, "actor": a} for r, a in d.approvals], key=lambda x: (x["revision"], x["actor"])),
            "current_votes": sorted(d.votes(d.rev))}
