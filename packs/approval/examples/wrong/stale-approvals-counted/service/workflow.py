"""service/workflow.py — the approval rules (harness/SERVICE.md), written by this application. Pure functions over a
document dict; the store decides nothing itself."""
DEFAULT_QUORUM = 2                 # a create without `quorum`; every version 1 document (service/migrate.py)
QUORUMS = range(2, 6)
NEEDS = {"submit": None, "approve": "approver", "reject": "approver", "publish": "publisher"}
FROM = {"submit": "draft", "approve": "in_review", "reject": "in_review", "publish": "approved"}


def votes(doc, rev): return sorted(a for r, a in doc["approvals"] if r == rev)


def create(actor_roles, actor, doc_id, title, body, quorum=DEFAULT_QUORUM):
    if "editor" not in actor_roles: return "ROLE", None
    return None, {"id": doc_id, "title": title, "status": "draft", "quorum": quorum, "revisions": [{"revision": 1, "author": actor, "body": body}], "approvals": []}


def apply(doc, op, actor, actor_roles, revision=None, body=None):
    """(reason or None, new document). A refusal returns the document unchanged."""
    cur = len(doc["revisions"]); author = doc["revisions"][-1]["author"]
    if op == "edit":
        if "editor" not in actor_roles: return "ROLE", doc
        if doc["status"] == "published": return "WRONG_STATE", doc
        return None, {**doc, "status": "draft", "revisions": doc["revisions"] + [{"revision": cur + 1, "author": actor, "body": body}]}
    if NEEDS[op] and NEEDS[op] not in actor_roles: return "ROLE", doc
    if revision != cur: return "STALE_REVISION", doc
    if doc["status"] != FROM[op]: return "WRONG_STATE", doc
    if op == "submit":
        return (None, {**doc, "status": "in_review"}) if actor == author else ("NOT_AUTHOR", doc)
    if op in ("approve", "reject") and actor == author: return "SEPARATION_OF_DUTIES", doc
    if op == "approve":
        if [cur, actor] in doc["approvals"]: return "ALREADY_APPROVED", doc
        ap = doc["approvals"] + [[cur, actor]]
        # DEFECT: the quorum counts approvals of every revision, so approvals of a superseded revision still count after an edit
        return None, {**doc, "approvals": ap, "status": "approved" if len({a for r, a in ap}) >= doc["quorum"] else "in_review"}
    if op == "reject": return None, {**doc, "status": "rejected"}
    return None, {**doc, "status": "published"}


def view(doc):
    if doc is None: return None
    cur = len(doc["revisions"])
    return {"id": doc["id"], "title": doc["title"], "status": doc["status"], "revision": cur, "quorum": doc["quorum"], "revisions": doc["revisions"],
            "approvals": [{"revision": r, "actor": a} for r, a in sorted(map(tuple, doc["approvals"]))], "current_votes": votes(doc, cur)}
