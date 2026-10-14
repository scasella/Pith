// profiles/node/store.mjs — the shipped Node.js integration profile: an fsync'd append-only journal. FROZEN.
//
// The same contract as profiles/python/store.py (harness/SERVICE.md), on a different stack:
//   - state is a journal of committed operations (JSON lines). An operation is appended and fsync'd BEFORE it is
//     acknowledged; on open the journal is replayed, and a torn last line (a crash mid-write, never acknowledged)
//     is discarded and truncated away
//   - operations are atomic because each method runs to completion without yielding: Node runs one JavaScript
//     turn at a time, and nothing between load, decide and append awaits. That is the profile's atomicity
//     argument; profiles/node/tests/ and the harness's concurrent bursts test it
//   - inputs are validated to the proof's domain before the verified core (bookingcore.js, translated from
//     spec/BookingCore.dfy) is called; request_id is the idempotency key of every operation; Valid is re-checked
//     on every result (defence in depth)
//   - each resource's buffer (interval-booking-core/v2) is journalled with it when it is created and never changed;
//     every book, cancel and move on the resource passes it to the core
//   - a journal the version 1 profile wrote (resources without a buffer) is refused until migrate() has upgraded it
//     (harness/SERVICE.md, "Upgrading from version 1"): replaying it as it is would have to guess a buffer
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { BookingSpec, BookingCore, _dafny, BigNumber } = require("./bookingcore.js");

export const MAX = 2 ** 53;
export const MAX_BUFFER = 1440;                                                         // minutes: one day
export class InvalidRequest extends Error {}
export class ConflictingReplay extends Error {}
export class Duplicate extends Error {}
export class Unknown extends Error {}
export class CorruptCore extends Error {}
export class Unrecognised extends Error {}

const WIRE = { Accepted: "ACCEPTED", Conflict: "CONFLICT", Invalid: "INVALID", NotActive: "NOT_ACTIVE" };
export function validateInt(x, name) {
  if (typeof x !== "number" || !Number.isInteger(x) || x < 0 || x >= MAX) throw new InvalidRequest(`${name} must be an integer in [0, 2^53), got ${JSON.stringify(x)}`);
  return x;
}
export function validateBuffer(x) {
  if (typeof x !== "number" || !Number.isInteger(x) || x < 0 || x > MAX_BUFFER) throw new InvalidRequest(`buffer must be an integer in [0, ${MAX_BUFFER}] (minutes), got ${JSON.stringify(x)}`);
  return x;
}
const big = (n) => new BigNumber(n);
const calendar = (rows) => _dafny.Seq.of(...rows.map(([i, s, e, a]) => BookingSpec.Slot.create_Slot(big(i), big(s), big(e), a)));
const rows = (cal) => Array.from(cal, (x) => [x.dtor_id.toNumber(), x.dtor_start.toNumber(), x.dtor_end.toNumber(), x.dtor_active]);
const outcome = (o) => [WIRE[String(o).replace(/^BookingSpec\.Outcome\./, "").replace(/\(.*$/, "")], o.is_Conflict ? o.dtor_with.toNumber() : null];
export function valid(rs, g = 0) {
  const act = rs.filter((r) => r[3]).map((r) => [r[1], r[2]]).sort((a, b) => a[0] - b[0]);
  return new Set(rs.map((r) => r[0])).size === rs.length && rs.every((r) => r[1] < r[2]) && act.every((x, k) => k === 0 || act[k - 1][1] + g <= x[0]);
}

// ---- the journal's versions ----
const isBuffer = (g) => Number.isInteger(g) && g >= 0 && g <= MAX_BUFFER;
function journalLines(text, where) {
  const cut = text.lastIndexOf("\n") + 1;                                     // a torn last line was never acknowledged
  return text.slice(0, cut).split("\n").filter((l) => l).map((line, n) => {
    let e; try { e = JSON.parse(line); } catch { throw new Unrecognised(`${where}: line ${n + 1} is not JSON`); }
    if (e === null || typeof e !== "object" || !Array.isArray(e.events)) throw new Unrecognised(`${where}: line ${n + 1} is not a journal entry`);
    if (e.resource && (!Number.isInteger(e.resource.id) || typeof e.resource.name !== "string")) throw new Unrecognised(`${where}: line ${n + 1} is not a resource entry`);
    return e;
  });
}

// Upgrade a version 1 journal at `file` in place to version 2: every resource entry gets buffer 0 (the version 1
// convention, so nothing already decided changes meaning: spec/BookingSpec.dfy BufferZeroIsHalfOpen); every other
// entry (bookings, the request ledger, the events) is kept byte for byte. The new journal is written beside the old,
// fsync'd and renamed over it, so an interrupted migration leaves one or the other. On a version 2 journal it changes
// nothing; anything else (not a journal this profile wrote, or a mix of versions) is Unrecognised, untouched.
export function migrate(file) {
  if (!fs.existsSync(file)) return "no state: nothing to migrate";
  const text = fs.readFileSync(file, "utf8"); const entries = journalLines(text, file);
  const res = entries.filter((e) => e.resource);
  const v1 = res.filter((e) => !("buffer" in e.resource)), v2 = res.filter((e) => isBuffer(e.resource.buffer));
  if (v1.length + v2.length !== res.length || (v1.length && v2.length)) throw new Unrecognised(`${file}: resource entries of neither or both versions`);
  if (!v1.length) return "already version 2: nothing to do";
  const lines = text.slice(0, text.lastIndexOf("\n") + 1).split("\n").filter((l) => l);
  const out = lines.map((line, n) => entries[n].resource ? JSON.stringify({ ...entries[n], resource: { ...entries[n].resource, buffer: 0 } }) : line);
  const tmp = `${file}.migrating`; const fd = fs.openSync(tmp, "w");
  fs.writeSync(fd, out.map((l) => l + "\n").join("")); fs.fsyncSync(fd); fs.closeSync(fd);
  fs.renameSync(tmp, file);
  const dir = fs.openSync(path.dirname(file), "r"); fs.fsyncSync(dir); fs.closeSync(dir);
  return `migrated ${v1.length} version 1 resources to buffer 0; ${entries.filter((e) => e.op).length} recorded results kept`;
}

export class Store {
  constructor(file) {
    this.path = file; this.resourcesById = new Map(); this.slots = new Map(); this.ops = new Map(); this.events = [];
    this.core = new BookingCore.Core();
    let text = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
    const cut = text.lastIndexOf("\n") + 1;
    if (cut < text.length) { fs.truncateSync(file, cut); text = text.slice(0, cut); }        // torn last line: never acknowledged
    for (const line of text.split("\n")) if (line) this.apply(JSON.parse(line));
    this.fd = fs.openSync(file, "a");
  }
  // ---- the journal: one line per committed operation; replaying it rebuilds every table ----
  apply(entry) {
    if (entry.resource && !isBuffer(entry.resource.buffer))
      throw new Unrecognised(`${this.path}: a resource without a buffer (version 1 state): upgrade it with migrate() first`);
    for (const ev of entry.events) this.events.push({ ...ev, seq: this.events.length + 1 });
    if (entry.resource) this.resourcesById.set(entry.resource.id, { name: entry.resource.name, buffer: entry.resource.buffer });
    for (const [i, rid, s, e, a] of entry.slots || []) this.slots.set(i, { id: i, resource: rid, start: s, end: e, active: a });
    if (entry.op) this.ops.set(entry.op.request_id, entry.op);
  }
  commit(entry) {
    fs.writeSync(this.fd, JSON.stringify(entry) + "\n"); fs.fsyncSync(this.fd);             // durable before acknowledged
    this.apply(entry);
  }
  // ---- reads ----
  resources() { return [...this.resourcesById].sort((a, b) => a[0] - b[0]).map(([id, r]) => ({ id, name: r.name, buffer: r.buffer })); }
  cal(rid) { return [...this.slots.values()].filter((x) => x.resource === rid).sort((a, b) => a.id - b.id).map((x) => [x.id, x.start, x.end, x.active]); }
  buffer(rid) { return this.resourcesById.get(rid).buffer; }
  resource(rid) {
    validateInt(rid, "resource");
    if (!this.resourcesById.has(rid)) return null;
    const r = this.resourcesById.get(rid);
    return { id: rid, name: r.name, buffer: r.buffer, bookings: this.cal(rid).map(([id, start, end, active]) => ({ id, start, end, active })) };
  }
  booking(bid) { validateInt(bid, "booking id"); const x = this.slots.get(bid); return x ? { ...x } : null; }
  eventsSince(since = 0) { return this.events.filter((e) => e.seq > since); }
  // ---- writes ----
  replay(requestId, kind, params) {
    const op = this.ops.get(requestId);
    if (!op) return null;
    if (op.kind !== kind || JSON.stringify(op.params) !== JSON.stringify(params)) throw new ConflictingReplay(`request_id ${requestId} was used for a different operation`);
    return { ...op.result, replayed: true };
  }
  finish(requestId, kind, params, result, rid, before, after, events) {
    if (!valid(after, this.buffer(rid))) throw new CorruptCore("the core's result violates Valid");
    const old = new Map(before.map((r) => [r[0], r]));
    const changed = after.filter((r) => !old.has(r[0]) || JSON.stringify(old.get(r[0])) !== JSON.stringify(r)).map(([i, s, e, a]) => [i, rid, s, e, a]);
    events.push({ type: "op.committed", request_id: requestId, resource: rid, active: after.filter((r) => r[3]).map((r) => [r[0], r[1], r[2]]) });
    this.commit({ op: { request_id: requestId, kind, params, result }, slots: changed, events });
    return { ...result, replayed: false };
  }
  createResource(rid, name, buffer = 0) {
    validateInt(rid, "resource"); validateBuffer(buffer);
    if (typeof name !== "string" || name.length === 0 || name.length > 200) throw new InvalidRequest("name must be a non-empty string of at most 200 characters");
    if (this.resourcesById.has(rid)) throw new Duplicate(String(rid));                       // the buffer is fixed at creation
    this.commit({ resource: { id: rid, name, buffer }, events: [{ type: "resource.created", resource: rid, name, buffer }] });
    return { id: rid, name, buffer };
  }
  book(requestId, rid, start, end) {
    [[requestId, "request_id"], [rid, "resource"], [start, "start"], [end, "end"]].forEach(([v, n]) => validateInt(v, n));
    const params = { resource: rid, start, end };
    const r = this.replay(requestId, "book", params); if (r) return r;
    if (!this.resourcesById.has(rid)) throw new Unknown(`resource ${rid}`);
    if (this.slots.has(requestId)) throw new ConflictingReplay(`booking ${requestId} exists`);
    const before = this.cal(rid);
    const [o, cal] = this.core.Book(calendar(before), big(this.buffer(rid)), big(requestId), big(start), big(end));
    const [name, withId] = outcome(o);
    const ev = { type: name === "ACCEPTED" ? "booking.accepted" : "booking.refused", request_id: requestId, resource: rid, start, end, outcome: name, conflicts_with: withId };
    return this.finish(requestId, "book", params, { request_id: requestId, booking_id: requestId, resource: rid, outcome: name, conflicts_with: withId }, rid, before, rows(cal), [ev]);
  }
  onBooking(requestId, bid, kind, params, decide) {
    validateInt(requestId, "request_id"); validateInt(bid, "booking id");
    const r = this.replay(requestId, kind, params); if (r) return r;
    const x = this.slots.get(bid); if (!x) throw new Unknown(`booking ${bid}`);
    const before = this.cal(x.resource);
    const [result, after, ev] = decide(x.resource, before, big(this.buffer(x.resource)));
    return this.finish(requestId, kind, params, result, x.resource, before, after, [ev]);
  }
  cancel(requestId, bid) {
    return this.onBooking(requestId, bid, "cancel", { booking_id: bid }, (rid, before, g) => {
      const [ok, cal] = this.core.Cancel(calendar(before), g, big(bid));
      return [{ request_id: requestId, booking_id: bid, cancelled: ok }, rows(cal), { type: ok ? "booking.cancelled" : "cancel.refused", request_id: requestId, booking_id: bid, resource: rid }];
    });
  }
  reschedule(requestId, bid, start, end) {
    validateInt(start, "start"); validateInt(end, "end");
    return this.onBooking(requestId, bid, "reschedule", { booking_id: bid, start, end }, (rid, before, g) => {
      const [o, cal] = this.core.Reschedule(calendar(before), g, big(bid), big(start), big(end));
      const [name, withId] = outcome(o); const after = rows(cal); const now = after.find((r) => r[0] === bid);
      return [{ request_id: requestId, booking_id: bid, outcome: name, conflicts_with: withId, start: now[1], end: now[2] }, after,
              { type: name === "ACCEPTED" ? "booking.moved" : "move.refused", request_id: requestId, booking_id: bid, resource: rid, start, end, outcome: name, conflicts_with: withId }];
    });
  }
}
