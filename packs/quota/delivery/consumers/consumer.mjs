// delivery/consumers/consumer.mjs — a programmer's use of the candidate's Node.js library. FROZEN.
// The twin of consumer.py: run by delivery/delivery_adapter.py AS THE CANDIDATE, never imported by the judge.
//
//     node delivery/consumers/consumer.mjs silent | quickstart | errors | values | growth
//     node delivery/consumers/consumer.mjs backoff '<json>' | persist-a '<json>' | persist-b '<dump text>' '<json>'
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const { Limiter, LimiterError, InvalidArgument, ClockRegression } = await import(pathToFileURL(join(ROOT, "lib", "limiter.mjs")).href);
const cmd = process.argv[2];
const out = (v) => process.stdout.write(JSON.stringify(v) + "\n");
const dec = (d) => [d.granted, d.remaining, d.retryAfter === undefined ? "undefined" : d.retryAfter];

function calls(lim, steps) {
  return steps.map(([key, now, cost]) => {
    try { return dec(lim.acquire(key, { now, cost })); }
    catch (e) { if (e instanceof LimiterError) return e.constructor.name; throw e; }
  });
}

if (cmd === "silent") {
  // nothing: importing is the whole test
} else if (cmd === "quickstart") {                       // harness/LIBRARY.md § The API, as written
  const lim = new Limiter({ limit: 3, window: 60 });
  const d = lim.acquire("alice", { now: 10 });
  const r = [dec(d), dec(lim.acquire("alice", { now: 10, cost: 2 })), dec(lim.acquire("alice", { now: 11 })), lim.peek("alice", { now: 11 })];
  const text = lim.dump();
  const lim2 = Limiter.load(text);
  r.push(lim2.peek("alice", { now: 70 }), dec(lim2.acquire("alice", { now: 70, cost: 3 })), lim.peek("alice", { now: 69 }));
  out(r);
} else if (cmd === "backoff") {
  const w = JSON.parse(process.argv[3]); const lim = new Limiter({ limit: w.limit, window: w.window }); let t = 0; const r = [];
  for (const [key, arrival, cost] of w.arrivals) {
    t = Math.max(t, arrival); let attempts = 0;
    for (;;) {
      const d = lim.acquire(key, { now: t, cost }); attempts++;
      if (d.granted) { r.push([t, attempts]); break; }
      if (d.retryAfter === null) { r.push([null, attempts]); break; }
      if (attempts > 3 || typeof d.retryAfter !== "number") { r.push(["gave up", attempts]); break; }
      t += d.retryAfter;                                  // wait exactly what the limiter said
    }
  }
  out(r);
} else if (cmd === "errors") {
  const lim = new Limiter({ limit: 2, window: 10 }); lim.acquire("k", { now: 50 }); const r = {};
  const tries = { limit: () => new Limiter({ limit: 0, window: 10 }), window: () => new Limiter({ limit: 1, window: -3 }),
                  key: () => lim.acquire("no spaces", { now: 60 }), cost: () => lim.acquire("k", { now: 60, cost: 0 }),
                  now: () => lim.acquire("k", { now: -1 }), text: () => Limiter.load("not a dump"), regression: () => lim.acquire("k", { now: 49 }) };
  for (const [name, f] of Object.entries(tries)) {
    try { f(); r[name] = { raised: null }; }
    catch (e) {
      if (e instanceof LimiterError) {
        r[name] = { raised: e.constructor.name, base: true, value_error: e instanceof Error, invalid: e instanceof InvalidArgument,
                    regression: e instanceof ClockRegression, argument: e.argument ?? null, clock: e.clock ?? null, message: String(e.message ?? "").trim().length > 0 };
      } else r[name] = { raised: e?.constructor?.name ?? typeof e, base: false };
    }
  }
  out(r);
} else if (cmd === "persist-a") {
  const w = JSON.parse(process.argv[3]); const lim = new Limiter({ limit: w.limit, window: w.window });
  const decisions = calls(lim, w.before); out({ decisions, dump: lim.dump() });
} else if (cmd === "persist-b") {
  const w = JSON.parse(process.argv[4]); const lim = Limiter.load(process.argv[3]);
  out({ decisions: calls(lim, w.after) });
} else if (cmd === "values") {
  const lim = new Limiter({ limit: 2, window: 10 });
  const a = lim.acquire("k", { now: 0 }); const before = dec(a);
  const b = lim.acquire("k", { now: 0, cost: 2 }); lim.acquire("k", { now: 3 }); lim.acquire("j", { now: 4 });
  out({ before, after: dec(a), second: dec(b) });
} else if (cmd === "growth") {
  const lim = new Limiter({ limit: 10, window: 10 }); let granted = 0;
  for (let i = 0; i < 20000; i++) if (lim.acquire("k", { now: i }).granted) granted++;
  out({ granted, dump_length: lim.dump().length });
}
