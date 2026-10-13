// Tests for pith-view.js: node --test obligations/app/lib/test_pith_view.mjs
// Each test names the interaction obligation (UI-CONTRACT.md) whose rule the transition implements.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const PV = createRequire(import.meta.url)("./pith-view.js");
const T = PV.transitions;
const acct = (id, holds = {}, available = 100) => ({ id, limit: 100, posted: 0, available, holds });

test("classify: 2xx answer, 4xx refusal, 5xx and no response unknown (I5)", () => {
  assert.equal(PV.classify(200), "OK"); assert.equal(PV.classify(201), "OK");
  assert.equal(PV.classify(409), "REJECTED"); assert.equal(PV.classify(404), "REJECTED");
  assert.equal(PV.classify(503), "UNKNOWN"); assert.equal(PV.classify(null), "UNKNOWN");
});

test("the draft never changes the loaded account or the rows' account (I1)", () => {
  let s = T.loadStarted(PV.initial(), 1); s = T.loadSucceeded(s, s.seq, acct(1, { 1: 20 }, 80));
  s = T.draft(s, 2);
  assert.equal(s.loaded.account, 1);
  assert.deepEqual(PV.rows(s), [{ account: 1, request: 1, amount: 20 }]);
});

test("a failed load of another account leaves the view bound to its own account (I2)", () => {
  let s = T.loadStarted(PV.initial(), 1); s = T.loadSucceeded(s, s.seq, acct(1, { 1: 20 }, 80));
  s = T.loadStarted(s, 2); s = T.loadFailed(s, s.seq, "HTTP 503");
  assert.equal(s.loaded.account, 1); assert.equal(s.loaded.state, "current");
  assert.equal(PV.rows(s)[0].account, 1); assert.equal(s.problem.account, 2);
});

test("a late response for a superseded load is ignored, in either order (I3)", () => {
  let s = T.loadStarted(PV.initial(), 1); const seqA = s.seq;
  s = T.loadStarted(s, 2); const seqB = s.seq;
  s = T.loadSucceeded(s, seqB, acct(2, { 1: 30 }, 70));
  s = T.loadSucceeded(s, seqA, acct(1, { 1: 20 }, 80));
  assert.equal(s.loaded.account, 2); assert.equal(s.loaded.data.available, 70);
  let t = T.loadStarted(PV.initial(), 1); const a = t.seq; t = T.loadStarted(t, 2); const b = t.seq;
  t = T.loadSucceeded(t, a, acct(1)); assert.equal(t.loaded, null);
  t = T.loadSucceeded(t, b, acct(2)); assert.equal(t.loaded.account, 2);
});

test("a refresh failure marks the view stale and leaves the receipt alone (I4)", () => {
  let s = T.loadStarted(PV.initial(), 1); s = T.loadSucceeded(s, s.seq, acct(1));
  s = T.opStarted(s, "authorize", 1, 7); s = T.opSettled(s, s.seq, 200, { decision: "AUTHORIZED", request_id: 7 });
  s = T.loadStarted(s, 1); s = T.loadFailed(s, s.seq, "HTTP 503");
  assert.equal(s.loaded.state, "stale"); assert.equal(s.receipt.decision, "AUTHORIZED"); assert.equal(s.receipt.account, 1);
  s = T.loadStarted(s, 1); s = T.loadSucceeded(s, s.seq, acct(1, { 7: 60 }, 40));
  assert.equal(s.loaded.state, "current"); assert.equal(s.receipt.request, 7);
});

test("outcome classes reach the receipt: UNKNOWN, REJECTED, decision (I5)", () => {
  let s = T.opStarted(PV.initial(), "authorize", 1, 1); s = T.opSettled(s, s.seq, null, null);
  assert.equal(s.receipt.decision, "UNKNOWN");
  s = T.opStarted(s, "authorize", 1, 1); s = T.opSettled(s, s.seq, 409, { error: "conflict" });
  assert.equal(s.receipt.decision, "REJECTED");
  s = T.opStarted(s, "authorize", 1, 1); s = T.opSettled(s, s.seq, 200, { decision: "DECLINED" });
  assert.equal(s.receipt.decision, "DECLINED");
  s = T.opStarted(s, "release", 1, 1); s = T.opSettled(s, s.seq, 200, { ok: true });
  assert.equal(s.receipt.decision, "DONE");
});

test("a receipt keeps its own account after a switch (I6)", () => {
  let s = T.loadStarted(PV.initial(), 1); s = T.loadSucceeded(s, s.seq, acct(1));
  s = T.opStarted(s, "authorize", 1, 3); s = T.opSettled(s, s.seq, 200, { decision: "AUTHORIZED" });
  s = T.loadStarted(s, 2); s = T.loadSucceeded(s, s.seq, acct(2));
  assert.equal(s.loaded.account, 2); assert.equal(s.receipt.account, 1); assert.equal(s.receipt.request, 3);
});

test("driver: authorize targets the loaded account, not the draft; a failed refresh keeps the receipt (I1, I4)", async () => {
  const calls = []; let failGet = false;
  const db = { 1: acct(1), 2: acct(2) };
  const fetch = async (path, init) => {
    calls.push(`${init.method} ${path}`);
    const ok = (status, body) => ({ status, json: async () => body });
    if (init.method === "GET") return failGet ? ok(503, { error: "down" }) : ok(200, db[path.split("/")[2]]);
    if (path.endsWith("/authorize")) { db[1] = acct(1, { 5: 60 }, 40); return ok(200, { decision: "AUTHORIZED", request_id: 5 }); }
    return ok(404, { error: "no" });
  };
  const v = PV.create({ fetch });
  await v.load(1); v.draft(2); failGet = true;
  const s = await v.authorize(5, 60);
  assert.ok(calls.includes("POST /accounts/1/authorize"));
  assert.ok(!calls.some((c) => c.startsWith("POST /accounts/2")));
  assert.equal(s.receipt.decision, "AUTHORIZED"); assert.equal(s.loaded.state, "stale");
});

test("driver: a network failure is UNKNOWN, never a decision (I5)", async () => {
  const fetch = async (path, init) => {
    if (init.method === "GET") return { status: 200, json: async () => acct(1) };
    throw new TypeError("network down");
  };
  const v = PV.create({ fetch }); await v.load(1);
  const s = await v.authorize(1, 10);
  assert.equal(s.receipt.decision, "UNKNOWN"); assert.equal(s.receipt.request, 1);
});
