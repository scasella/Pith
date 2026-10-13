// service/workflow.mjs — the approval rules (harness/SERVICE.md), as pure functions over a document object.
// Revisions carry their own approval sets here (a different representation from the Python example on purpose).
export const DEFAULT_QUORUM = 2;   // a create without `quorum`; every version 1 document (service/migrate.mjs)
export const isQuorum = (q) => Number.isInteger(q) && q >= 2 && q <= 5;
const NEEDS = { submit: null, approve: "approver", reject: "approver", publish: "publisher" };
const FROM = { submit: "draft", approve: "in_review", reject: "in_review", publish: "approved" };

const current = (doc) => doc.revisions[doc.revisions.length - 1];

export function create(roles, actor, id, title, body, quorum = DEFAULT_QUORUM) {
  if (!roles.has("editor")) return ["ROLE", null];
  return [null, { id, title, status: "draft", quorum, revisions: [{ revision: 1, author: actor, body, approvedBy: [] }] }];
}

export function apply(doc, op, actor, roles, revision, body) {
  const cur = current(doc);
  if (op === "edit") {
    if (!roles.has("editor")) return ["ROLE", doc];
    if (doc.status === "published") return ["WRONG_STATE", doc];
    return [null, { ...doc, status: "draft", revisions: [...doc.revisions, { revision: cur.revision + 1, author: actor, body, approvedBy: [] }] }];
  }
  if (NEEDS[op] && !roles.has(NEEDS[op])) return ["ROLE", doc];
  if (revision !== cur.revision) return ["STALE_REVISION", doc];
  if (doc.status !== FROM[op]) return ["WRONG_STATE", doc];
  if (op === "submit") return actor === cur.author ? [null, { ...doc, status: "in_review" }] : ["NOT_AUTHOR", doc];
  if ((op === "approve" || op === "reject") && actor === cur.author) return ["SEPARATION_OF_DUTIES", doc];
  if (op === "approve") {
    if (cur.approvedBy.includes(actor)) return ["ALREADY_APPROVED", doc];
    const next = { ...cur, approvedBy: [...cur.approvedBy, actor] };
    return [null, { ...doc, revisions: [...doc.revisions.slice(0, -1), next], status: next.approvedBy.length >= doc.quorum ? "approved" : "in_review" }];
  }
  if (op === "reject") return [null, { ...doc, status: "rejected" }];
  return [null, { ...doc, status: "published" }];
}

export function view(doc) {
  if (!doc) return null;
  const cur = current(doc);
  const approvals = doc.revisions.flatMap((r) => r.approvedBy.map((a) => ({ revision: r.revision, actor: a })))
    .sort((x, y) => x.revision - y.revision || (x.actor < y.actor ? -1 : x.actor > y.actor ? 1 : 0));
  return { id: doc.id, title: doc.title, status: doc.status, revision: cur.revision, quorum: doc.quorum,
           revisions: doc.revisions.map(({ revision, author, body }) => ({ revision, author, body })),
           approvals, current_votes: [...cur.approvedBy].sort() };
}
