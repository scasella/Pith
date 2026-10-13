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
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { BookingSpec, BookingCore, _dafny, BigNumber } = require("./bookingcore.js");

export const MAX = 2 ** 53;
export class InvalidRequest extends Error {}
export class ConflictingReplay extends Error {}
export class Duplicate extends Error {}
export class Unknown extends Error {}
export class CorruptCore extends Error {}

const WIRE = { Accepted: "ACCEPTED", Conflict: "CONFLICT", Invalid: "INVALID", NotActive: "NOT_ACTIVE" };
export function validateInt(x, name) {
  if (typeof x !== "number" || !Number.isInteger(x) || x < 0 || x >= MAX) throw new InvalidRequest(`${name} must be an integer in [0, 2^53), got ${JSON.stringify(x)}`);
  return x;
}
const big = (n) => new BigNumber(n);
const calendar = (rows) => _dafny.Seq.of(...rows.map(([i, s, e, a]) => BookingSpec.Slot.create_Slot(big(i), big(s), big(e), a)));
const rows = (cal) => Array.from(cal, (x) => [x.dtor_id.toNumber(), x.dtor_start.toNumber(), x.dtor_end.toNumber(), x.dtor_active]);
const outcome = (o) => [WIRE[String(o).replace(/^BookingSpec\.Outcome\./, "").replace(/\(.*$/, "")], o.is_Conflict ? o.dtor_with.toNumber() : null];
export function valid(rs) {
  const act = rs.filter((r) => r[3]).map((r) => [r[1], r[2]]).sort((a, b) => a[0] - b[0]);
  return new Set(rs.map((r) => r[0])).size === rs.length && rs.every((r) => r[1] < r[2]) && act.every((x, k) => k === 0 || act[k - 1][1] <= x[0]);
}

export class Store {
  constructor(path) {
    this.path = path; this.resourcesById = new Map(); this.slots = new Map(); this.ops = new Map(); this.events = [];
    this.core = new BookingCore.Core();
    let text = fs.existsSync(path) ? fs.readFileSync(path, "utf8") : "";
    const cut = text.lastIndexOf("\n") + 1;
    if (cut < text.length) { fs.truncateSync(path, cut); text = text.slice(0, cut); }        // torn last line: never acknowledged
    for (const line of text.split("\n")) if (line) this.apply(JSON.parse(line));
    this.fd = fs.openSync(path, "a");
  }
  // ---- the journal: one line per committed operation; replaying it rebuilds every table ----
  apply(entry) {
    for (const ev of entry.events) this.events.push({ ...ev, seq: this.events.length + 1 });
    if (entry.resource) this.resourcesById.set(entry.resource.id, entry.resource.name);
    for (const [i, rid, s, e, a] of entry.slots || []) this.slots.set(i, { id: i, resource: rid, start: s, end: e, active: a });
    if (entry.op) this.ops.set(entry.op.request_id, entry.op);
  }
  commit(entry) {
    fs.writeSync(this.fd, JSON.stringify(entry) + "\n"); fs.fsyncSync(this.fd);             // durable before acknowledged
    this.apply(entry);
  }
  // ---- reads ----
  resources() { return [...this.resourcesById].sort((a, b) => a[0] - b[0]).map(([id, name]) => ({ id, name })); }
  cal(rid) { return [...this.slots.values()].filter((x) => x.resource === rid).sort((a, b) => a.id - b.id).map((x) => [x.id, x.start, x.end, x.active]); }
  resource(rid) {
    validateInt(rid, "resource");
    if (!this.resourcesById.has(rid)) return null;
    return { id: rid, name: this.resourcesById.get(rid), bookings: this.cal(rid).map(([id, start, end, active]) => ({ id, start, end, active })) };
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
    if (!valid(after)) throw new CorruptCore("the core's result violates Valid");
    const old = new Map(before.map((r) => [r[0], r]));
    const changed = after.filter((r) => !old.has(r[0]) || JSON.stringify(old.get(r[0])) !== JSON.stringify(r)).map(([i, s, e, a]) => [i, rid, s, e, a]);
    events.push({ type: "op.committed", request_id: requestId, resource: rid, active: after.filter((r) => r[3]).map((r) => [r[0], r[1], r[2]]) });
    this.commit({ op: { request_id: requestId, kind, params, result }, slots: changed, events });
    return { ...result, replayed: false };
  }
  createResource(rid, name) {
    validateInt(rid, "resource");
    if (typeof name !== "string" || name.length === 0 || name.length > 200) throw new InvalidRequest("name must be a non-empty string of at most 200 characters");
    if (this.resourcesById.has(rid)) throw new Duplicate(String(rid));
    this.commit({ resource: { id: rid, name }, events: [{ type: "resource.created", resource: rid, name }] });
    return { id: rid, name };
  }
  book(requestId, rid, start, end) {
    [[requestId, "request_id"], [rid, "resource"], [start, "start"], [end, "end"]].forEach(([v, n]) => validateInt(v, n));
    const params = { resource: rid, start, end };
    const r = this.replay(requestId, "book", params); if (r) return r;
    if (!this.resourcesById.has(rid)) throw new Unknown(`resource ${rid}`);
    if (this.slots.has(requestId)) throw new ConflictingReplay(`booking ${requestId} exists`);
    const before = this.cal(rid);
    const [o, cal] = this.core.Book(calendar(before), big(requestId), big(start), big(end));
    const [name, withId] = outcome(o);
    const ev = { type: name === "ACCEPTED" ? "booking.accepted" : "booking.refused", request_id: requestId, resource: rid, start, end, outcome: name, conflicts_with: withId };
    return this.finish(requestId, "book", params, { request_id: requestId, booking_id: requestId, resource: rid, outcome: name, conflicts_with: withId }, rid, before, rows(cal), [ev]);
  }
  onBooking(requestId, bid, kind, params, decide) {
    validateInt(requestId, "request_id"); validateInt(bid, "booking id");
    const r = this.replay(requestId, kind, params); if (r) return r;
    const x = this.slots.get(bid); if (!x) throw new Unknown(`booking ${bid}`);
    const before = this.cal(x.resource);
    const [result, after, ev] = decide(x.resource, before);
    return this.finish(requestId, kind, params, result, x.resource, before, after, [ev]);
  }
  cancel(requestId, bid) {
    return this.onBooking(requestId, bid, "cancel", { booking_id: bid }, (rid, before) => {
      const [ok, cal] = this.core.Cancel(calendar(before), big(bid));
      return [{ request_id: requestId, booking_id: bid, cancelled: ok }, rows(cal), { type: ok ? "booking.cancelled" : "cancel.refused", request_id: requestId, booking_id: bid, resource: rid }];
    });
  }
  reschedule(requestId, bid, start, end) {
    validateInt(start, "start"); validateInt(end, "end");
    return this.onBooking(requestId, bid, "reschedule", { booking_id: bid, start, end }, (rid, before) => {
      const [o, cal] = this.core.Reschedule(calendar(before), big(bid), big(start), big(end));
      const [name, withId] = outcome(o); const after = rows(cal); const now = after.find((r) => r[0] === bid);
      return [{ request_id: requestId, booking_id: bid, outcome: name, conflicts_with: withId, start: now[1], end: now[2] }, after,
              { type: name === "ACCEPTED" ? "booking.moved" : "move.refused", request_id: requestId, booking_id: bid, resource: rid, start, end, outcome: name, conflicts_with: withId }];
    });
  }
}
