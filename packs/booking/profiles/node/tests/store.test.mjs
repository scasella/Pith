// profiles/node/tests/store.test.mjs — in-process tests of the shipped Node.js profile (journal store). FROZEN.
// They establish what the proof assumes of its surroundings (spec/tcb.yaml) on this stack: operations are atomic
// against the latest committed calendar and its resource's buffer, committed operations survive reopening and a torn
// journal tail, replays never reach the core, invalid input changes nothing, and a version 1 journal is upgraded by
// migrate() and refused until it is. Judged when app.manifest.yaml says runtime: node, profile: shipped.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { Store, ConflictingReplay, Duplicate, InvalidRequest, Unknown, Unrecognised, valid, migrate } from "../store.mjs";
const { BookingSpec, BookingCore, _dafny, BigNumber } = createRequire(import.meta.url)("../bookingcore.js");

const BUFFER = { 1: 0, 2: 10 };                   // resource 1 keeps version 1's convention; resource 2 has a turnaround buffer
const tmp = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "bk-")), "journal.jsonl");
function fresh(p = tmp()) { const s = new Store(p); s.createResource(1, "Room"); s.createResource(2, "Other", BUFFER[2]); return s; }
const cal = (s, rid) => s.resource(rid).bookings.map((b) => [b.id, b.start, b.end, b.active]);

test("requests for one interval interleaved with awaits accept exactly one", async () => {
  const s = fresh();
  const res = await Promise.all(Array.from({ length: 32 }, (_, i) => new Promise((r) => setImmediate(() => r(s.book(100 + i, 1, 600, 660))))));
  assert.equal(res.filter((r) => r.outcome === "ACCEPTED").length, 1);
  assert.ok(valid(cal(s, 1)));
});

test("requests within one buffer interleaved with awaits accept exactly one", async () => {
  const s = fresh();                              // [600, 660) and [665, 700) are 5 apart: one of them, with buffer 10
  const res = await Promise.all(Array.from({ length: 32 }, (_, i) => new Promise((r) => setImmediate(() => r(s.book(100 + i, 2, ...(i % 2 ? [600, 660] : [665, 700])))))));
  assert.equal(res.filter((r) => r.outcome === "ACCEPTED").length, 1);
  assert.ok(valid(cal(s, 2), BUFFER[2]));
});

test("reopen preserves state, ops, events and buffers; a torn tail is discarded", () => {
  const p = tmp(); let s = fresh(p);
  s.book(1, 1, 600, 660); s.book(2, 1, 630, 700); s.cancel(3, 1); s.book(4, 1, 630, 700); s.book(5, 2, 600, 660);
  const view = JSON.stringify(s.resource(1)), evs = JSON.stringify(s.eventsSince()), res = JSON.stringify(s.resources());
  fs.appendFileSync(p, '{"op":{"request_id":6,"kind":"book"');                // a crash in the middle of an append
  s = new Store(p);
  assert.equal(JSON.stringify(s.resource(1)), view); assert.equal(JSON.stringify(s.eventsSince()), evs); assert.equal(JSON.stringify(s.resources()), res);
  assert.deepEqual(s.resources(), [{ id: 1, name: "Room", buffer: 0 }, { id: 2, name: "Other", buffer: 10 }]);
  assert.equal(s.book(1, 1, 600, 660).replayed, true); assert.equal(s.book(6, 1, 0, 10).outcome, "ACCEPTED");
  assert.equal(s.book(7, 2, 669, 700).outcome, "CONFLICT"); assert.equal(s.book(8, 2, 670, 700).outcome, "ACCEPTED");
  assert.ok(fs.readFileSync(p, "utf8").endsWith("\n"));
});

test("the buffer is fixed at creation", () => {
  const s = fresh();
  assert.throws(() => s.createResource(2, "Other", 0), Duplicate);
  assert.equal(s.resource(2).buffer, BUFFER[2]); assert.deepEqual(s.createResource(3, "Third"), { id: 3, name: "Third", buffer: 0 });
});

test("a replay never reaches the core; a different reuse of a request id is refused", () => {
  const s = fresh(); s.book(1, 1, 600, 660);
  s.core = null;
  assert.equal(s.book(1, 1, 600, 660).replayed, true);
  assert.throws(() => s.book(1, 1, 600, 661), ConflictingReplay);
  assert.throws(() => s.cancel(1, 1), ConflictingReplay);
});

test("invalid input changes nothing", () => {
  for (const bad of [-1, 2 ** 53, 1.5, "1", true, null]) {
    const s = fresh(); const n = s.eventsSince().length;
    for (const call of [() => s.book(bad, 1, 0, 10), () => s.book(9, 1, bad, 10), () => s.book(9, 1, 0, bad), () => s.reschedule(9, bad, 0, 10), () => s.createResource(9, "x", bad)])
      assert.throws(call, InvalidRequest);
    assert.throws(() => s.createResource(9, "x", 1441), InvalidRequest);
    assert.equal(s.eventsSince().length, n); assert.equal(s.resource(9), null);
  }
});

test("unknown resource and booking", () => {
  const s = fresh();
  assert.throws(() => s.book(1, 99, 0, 10), Unknown); assert.throws(() => s.cancel(2, 99), Unknown);
});

// What the version 1 profile journalled: two touching bookings (free at buffer 0), a refusal, a cancellation, and a
// torn tail from a crash mid-append.
const V1 = [
  { resource: { id: 1, name: "Room" }, events: [{ type: "resource.created", resource: 1, name: "Room" }] },
  { op: { request_id: 1, kind: "book", params: { resource: 1, start: 600, end: 660 }, result: { request_id: 1, booking_id: 1, resource: 1, outcome: "ACCEPTED", conflicts_with: null } }, slots: [[1, 1, 600, 660, true]], events: [{ type: "booking.accepted", request_id: 1 }] },
  { op: { request_id: 2, kind: "book", params: { resource: 1, start: 660, end: 720 }, result: { request_id: 2, booking_id: 2, resource: 1, outcome: "ACCEPTED", conflicts_with: null } }, slots: [[2, 1, 660, 720, true]], events: [{ type: "booking.accepted", request_id: 2 }] },
  { op: { request_id: 4, kind: "book", params: { resource: 1, start: 630, end: 690 }, result: { request_id: 4, booking_id: 4, resource: 1, outcome: "CONFLICT", conflicts_with: 1 } }, slots: [], events: [{ type: "booking.refused", request_id: 4 }] },
  { op: { request_id: 5, kind: "cancel", params: { booking_id: 2 }, result: { request_id: 5, booking_id: 2, cancelled: true } }, slots: [[2, 1, 660, 720, false]], events: [{ type: "booking.cancelled", request_id: 5 }] },
];

test("a version 1 journal is refused until migrated, then kept with buffer 0", () => {
  const p = tmp(); fs.writeFileSync(p, V1.map((e) => JSON.stringify(e) + "\n").join("") + '{"op":{"request_id":9');
  assert.throws(() => new Store(p), Unrecognised);
  assert.match(migrate(p), /^migrated 1 /); const once = fs.readFileSync(p, "utf8");
  assert.match(migrate(p), /^already version 2/); assert.equal(fs.readFileSync(p, "utf8"), once);
  const s = new Store(p);
  assert.deepEqual(s.resources(), [{ id: 1, name: "Room", buffer: 0 }]); assert.deepEqual(cal(s, 1), [[1, 600, 660, true], [2, 660, 720, false]]);
  assert.deepEqual(s.book(4, 1, 630, 690), { request_id: 4, booking_id: 4, resource: 1, outcome: "CONFLICT", conflicts_with: 1, replayed: true });
  assert.equal(s.cancel(5, 2).replayed, true); assert.equal(s.book(6, 1, 660, 700).outcome, "ACCEPTED");      // touching at buffer 0
  assert.deepEqual(s.eventsSince()[0], { type: "resource.created", resource: 1, name: "Room", seq: 1 });
});

test("migrate refuses a journal it does not recognise and leaves it untouched", () => {
  for (const text of ["this is not a booking database\n", '{"no":"events"}\n', JSON.stringify(V1[0]) + "\n" + JSON.stringify({ ...V1[0], resource: { id: 2, name: "B", buffer: 5 } }) + "\n"]) {
    const p = tmp(); fs.writeFileSync(p, text);
    assert.throws(() => migrate(p), Unrecognised); assert.equal(fs.readFileSync(p, "utf8"), text);
  }
  const missing = tmp(); assert.match(migrate(missing), /^no state/); assert.ok(!fs.existsSync(missing));
});

test("the store agrees with the verified core applied in order (seeded random operations)", () => {
  let seed = 7; const rnd = (n) => (seed = (seed * 1103515245 + 12345) % 2147483648) % n;
  const big = (n) => new BigNumber(n);
  const toCal = (rows) => _dafny.Seq.of(...rows.map(([i, s, e, a]) => BookingSpec.Slot.create_Slot(big(i), big(s), big(e), a)));
  const fromCal = (c) => Array.from(c, (x) => [x.dtor_id.toNumber(), x.dtor_start.toNumber(), x.dtor_end.toNumber(), x.dtor_active]);
  for (let run = 0; run < 40; run++) {
    const s = fresh(); const k = new BookingCore.Core(); const model = { 1: [], 2: [] }; const owner = new Map();
    for (let n = 0; n < 40; n++) {
      const op = ["book", "cancel", "move"][rnd(3)], rid = 1 + rnd(2), bid = 1 + rnd(12), a = rnd(21) * 10, b = rnd(21) * 10, rq = 1000 + n;
      if (op === "book") {
        if (owner.has(bid)) continue;
        const r = s.book(bid, rid, a, b); const [o, c] = k.Book(toCal(model[rid]), big(BUFFER[rid]), big(bid), big(a), big(b));
        model[rid] = fromCal(c); owner.set(bid, rid); assert.equal(r.outcome === "ACCEPTED", o.is_Accepted);
      } else if (owner.has(bid) && model[owner.get(bid)].some((x) => x[0] === bid)) {
        const rr = owner.get(bid);
        if (op === "cancel") { const r = s.cancel(rq, bid); const [ok, c] = k.Cancel(toCal(model[rr]), big(BUFFER[rr]), big(bid)); assert.equal(r.cancelled, ok); model[rr] = fromCal(c); }
        else { const r = s.reschedule(rq, bid, a, b); const [o, c] = k.Reschedule(toCal(model[rr]), big(BUFFER[rr]), big(bid), big(a), big(b)); assert.equal(r.outcome === "ACCEPTED", o.is_Accepted); model[rr] = fromCal(c); }
      }
      for (const r of [1, 2]) { assert.deepEqual(cal(s, r), [...model[r]].sort((x, y) => x[0] - y[0])); assert.ok(valid(cal(s, r), BUFFER[r])); }
    }
  }
});
