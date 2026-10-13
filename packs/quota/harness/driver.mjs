// harness/driver.mjs — runs one program against the candidate's Node.js library. FROZEN. The twin of harness/driver.py:
// pack code started AS THE CANDIDATE (gate/sandbox.py:run_as_candidate_full); the only pack code that imports the
// candidate's library, in the candidate's process, never the judge's.
//
//     node harness/driver.mjs '<json program>'       prints one JSON line: {"results": [...]}
//
// Same steps and result shapes as driver.py. "burst" runs its calls one after another (a Node.js limiter is
// synchronous: there is no thread to interleave with), so it reports exactly what sequential calls would.
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const L = await import(pathToFileURL(join(ROOT, "lib", "limiter.mjs")).href);

function err(e) {
  let name = "other";
  for (const n of ["ClockRegression", "InvalidArgument"]) {
    if (typeof L[n] === "function" && e instanceof L[n]) { name = n; break; }
  }
  const out = { error: name, type: e?.constructor?.name ?? typeof e, message: String(e?.message ?? e).slice(0, 200),
                is_base: typeof L.LimiterError === "function" && e instanceof L.LimiterError };
  for (const a of ["argument", "clock"]) if (e && typeof e === "object" && a in e) out[a] = e[a];
  return out;
}

// undefined is reported as the string "undefined" (JSON would drop it); the contract requires null
const und = (v) => (v === undefined ? "undefined" : v);
const decision = (d) => ({ granted: und(d.granted), remaining: und(d.remaining), retry_after: und(d.retryAfter) });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const prog = JSON.parse(process.argv[2]);
const lims = new Map(), dumps = new Map(), results = [];
for (const s of prog.steps) {
  let r;
  try {
    const lim = lims.get(s.id);
    switch (s.op) {
      case "new": lims.set(s.id, new L.Limiter({ limit: s.limit, window: s.window })); r = { ok: null }; break;
      case "acquire": r = { ok: decision(lim.acquire(s.key, "cost" in s ? { now: s.now, cost: s.cost } : { now: s.now })) }; break;
      case "peek": r = { ok: lim.peek(s.key, { now: s.now }) }; break;
      case "dump": { const t = lim.dump(); dumps.set(s.id, t); r = { ok: { type: typeof t === "string" ? "str" : typeof t, text: typeof t === "string" ? t : null } }; break; }
      case "load": {
        let t = "from" in s ? dumps.get(s.from) : s.text;
        if (s.truncate && typeof t === "string") t = t.slice(0, Math.floor(t.length / 2));
        lims.set(s.id, L.Limiter.load(t)); r = { ok: null }; break;
      }
      case "burst": {
        let granted = 0; const errors = [];
        for (let t = 0; t < s.threads; t++) for (let j = 0; j < s.calls; j++) {
          const k = s.keys ? `${s.key}${j % s.keys}` : s.key;
          try { if (lim.acquire(k, { now: s.now, cost: s.cost }).granted) granted++; } catch (e) { errors.push(String(e)); }
        }
        r = { ok: { granted, errors: errors.slice(0, 3) } }; break;
      }
      case "sleep": await sleep(s.ms); r = { ok: null }; break;
      default: r = { error: "driver", message: `unknown op ${s.op}` };
    }
  } catch (e) {
    r = err(e);
  }
  try { JSON.stringify(r); } catch { r = { error: "driver", message: "result is not plain data" }; }
  results.push(r);
}
process.stdout.write(JSON.stringify({ results }) + "\n");
