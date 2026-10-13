// service/journal.mjs — state as an append-only journal of decided commands. Node runs one command at a time on its
// event loop, so each decision sees the latest committed state; a record is written and fsynced before the answer
// goes out, and a torn last line (a crash mid-write) is cut off on open.
import fs from "node:fs";
import * as W from "./workflow.mjs";

export class Invalid extends Error {}
export class Conflict extends Error {}
export class Missing extends Error {}

const NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ROLES = new Set(["editor", "approver", "publisher"]);
const name = (x, what) => { if (typeof x !== "string" || !NAME.test(x)) throw new Invalid(`${what} must match ${NAME}`); return x; };
const int = (x, what) => { if (!Number.isSafeInteger(x) || x < 0) throw new Invalid(`${what} must be an integer in [0, 2^53)`); return x; };
const text = (x, what) => { if (typeof x !== "string" || x.length > 10000) throw new Invalid(`${what} must be a string of at most 10000 characters`); return x; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export class Journal {
  constructor(path) {
    this.actors = new Map(); this.docs = new Map(); this.ops = new Map(); this.events = [];
    let raw = fs.existsSync(path) ? fs.readFileSync(path, "utf8") : "";
    const end = raw.lastIndexOf("\n") + 1;
    if (end < raw.length) { fs.truncateSync(path, end); raw = raw.slice(0, end); }
    for (const line of raw.split("\n")) if (line) this.#replay(JSON.parse(line));
    this.fd = fs.openSync(path, "a");
  }
  #replay(rec) {
    if (rec.t === "actor") this.actors.set(rec.id, rec.roles);
    else { this.ops.set(rec.rq, { params: rec.params, result: rec.result }); if (rec.doc) this.docs.set(rec.doc.id, rec.doc); }
    for (const e of rec.events) this.events.push({ ...e, seq: this.events.length + 1 });
  }
  #commit(rec) {
    fs.writeSync(this.fd, JSON.stringify(rec) + "\n"); fs.fsyncSync(this.fd); this.#replay(rec);
  }
  roles(id) { return new Set(this.actors.get(id) || []); }

  addActor(id, roles) {
    name(id, "id");
    if (!Array.isArray(roles) || !roles.every((r) => ROLES.has(r))) throw new Invalid("roles must be a list of editor, approver, publisher");
    if (this.actors.has(id)) throw new Conflict(`actor ${id} exists`);
    const rs = [...new Set(roles)].sort();
    this.#commit({ t: "actor", id, roles: rs, events: [{ type: "actor.registered", actor: id, roles: rs }] });
    return { id, roles: rs };
  }
  listActors() { return [...this.actors].sort(([a], [b]) => (a < b ? -1 : 1)).map(([id, roles]) => ({ id, roles })); }
  document(id) { name(id, "document id"); return W.view(this.docs.get(id)); }
  eventsSince(n) { return this.events.filter((e) => e.seq > n); }

  #command(rq, params, decide) {
    int(rq, "request_id");
    const prior = this.ops.get(rq);
    if (prior) { if (!same(prior.params, params)) throw new Conflict(`request_id ${rq} was used for another command`); return { ...prior.result, replayed: true }; }
    const [reason, doc] = decide();
    const result = { request_id: rq, outcome: reason ? "REFUSED" : "OK", reason, document: W.view(doc) };
    const events = [{ type: "command.decided", request_id: rq, command: params.op, document: params.id, actor: params.actor, outcome: result.outcome, reason },
                    { type: "op.committed", request_id: rq, document: params.id, status: doc ? doc.status : null, revision: doc ? doc.revisions.length : null }];
    this.#commit({ t: "op", rq, params, result, doc: reason ? null : doc, events });
    return { ...result, replayed: false };
  }
  create(rq, id, actor, title, body) {
    name(id, "id"); name(actor, "actor"); text(title, "title"); text(body, "body"); int(rq, "request_id");
    const params = { op: "create", id, actor, title, body };
    return this.#command(rq, params, () => {
      if (this.docs.has(id)) throw new Conflict(`document ${id} exists`);
      return W.create(this.roles(actor), actor, id, title, body);
    });
  }
  command(op, rq, id, actor, revision, body) {
    name(id, "document id"); name(actor, "actor"); int(rq, "request_id");
    if (op === "edit") text(body, "body"); else int(revision, "revision");
    const params = op === "edit" ? { op, id, actor, body } : { op, id, actor, revision };
    return this.#command(rq, params, () => {
      const doc = this.docs.get(id);
      if (!doc) throw new Missing(`unknown document ${id}`);
      return W.apply(doc, op, actor, this.roles(actor), revision, body);
    });
  }
}
