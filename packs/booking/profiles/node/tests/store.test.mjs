// profiles/node/tests/store.test.mjs — in-process tests of the shipped Node.js profile (journal store). FROZEN.
// They establish what the proof assumes of its surroundings (spec/tcb.yaml) on this stack: operations are atomic
// against the latest committed calendar, committed operations survive reopening and a torn journal tail, replays
// never reach the core, invalid input changes nothing. Judged when app.manifest.yaml says runtime: node, profile: shipped.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { Store, ConflictingReplay, InvalidRequest, Unknown, valid } from "../store.mjs";
const { BookingSpec, BookingCore, _dafny, BigNumber } = createRequire(import.meta.url)("../bookingcore.js");

const tmp = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "bk-")), "journal.jsonl");
function fresh(p = tmp()) { const s = new Store(p); s.createResource(1, "Room"); s.createResource(2, "Other"); return s; }
const cal = (s, rid) => s.resource(rid).bookings.map((b) => [b.id, b.start, b.end, b.active]);

test("requests for one interval interleaved with awaits accept exactly one", async () => {
  const s = fresh();
  const res = await Promise.all(Array.from({ length: 32 }, (_, i) => new Promise((r) => setImmediate(() => r(s.book(100 + i, 1, 600, 660))))));
  assert.equal(res.filter((r) => r.outcome === "ACCEPTED").length, 1);
  assert.ok(valid(cal(s, 1)));
});

test("reopen preserves state, ops and events; a torn tail is discarded", () => {
  const p = tmp(); let s = fresh(p);
  s.book(1, 1, 600, 660); s.book(2, 1, 630, 700); s.cancel(3, 1); s.book(4, 1, 630, 700);
  const view = JSON.stringify(s.resource(1)), evs = JSON.stringify(s.eventsSince());
  fs.appendFileSync(p, '{"op":{"request_id":5,"kind":"book"');                // a crash in the middle of an append
  s = new Store(p);
  assert.equal(JSON.stringify(s.resource(1)), view); assert.equal(JSON.stringify(s.eventsSince()), evs);
  assert.equal(s.book(1, 1, 600, 660).replayed, true); assert.equal(s.book(5, 1, 0, 10).outcome, "ACCEPTED");
  assert.ok(fs.readFileSync(p, "utf8").endsWith("\n"));
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
    for (const call of [() => s.book(bad, 1, 0, 10), () => s.book(9, 1, bad, 10), () => s.book(9, 1, 0, bad), () => s.reschedule(9, bad, 0, 10)])
      assert.throws(call, InvalidRequest);
    assert.equal(s.eventsSince().length, n);
  }
});

test("unknown resource and booking", () => {
  const s = fresh();
  assert.throws(() => s.book(1, 99, 0, 10), Unknown); assert.throws(() => s.cancel(2, 99), Unknown);
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
        const r = s.book(bid, rid, a, b); const [o, c] = k.Book(toCal(model[rid]), big(bid), big(a), big(b));
        model[rid] = fromCal(c); owner.set(bid, rid); assert.equal(r.outcome === "ACCEPTED", o.is_Accepted);
      } else if (owner.has(bid) && model[owner.get(bid)].some((x) => x[0] === bid)) {
        const rr = owner.get(bid);
        if (op === "cancel") { const r = s.cancel(rq, bid); const [ok, c] = k.Cancel(toCal(model[rr]), big(bid)); assert.equal(r.cancelled, ok); model[rr] = fromCal(c); }
        else { const r = s.reschedule(rq, bid, a, b); const [o, c] = k.Reschedule(toCal(model[rr]), big(bid), big(a), big(b)); assert.equal(r.outcome === "ACCEPTED", o.is_Accepted); model[rr] = fromCal(c); }
      }
      for (const r of [1, 2]) { assert.deepEqual(cal(s, r), [...model[r]].sort((x, y) => x[0] - y[0])); assert.ok(valid(cal(s, r))); }
    }
  }
});
