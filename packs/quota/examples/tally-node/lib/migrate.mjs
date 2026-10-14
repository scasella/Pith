// lib/migrate.mjs --state DIR: convert stored version 1 dumps ("tally/1") to this version's format in place.
//
// harness/LIBRARY.md, "Upgrading from version 1". Each <name>.dump in DIR is read; a version 1 dump
// "tally/1|limit;window;clock|key=t:c,...|..." becomes "tally/2|limit;window;clock||key=t:c,...|...": the same
// configuration, clock and tallies, and an empty section of per-key limits. A version 2 dump is left as it is (so a
// second run changes nothing). Anything else in DIR refuses the whole run before a single file is written.
import { readdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Limiter, LimiterError } from "./limiter.mjs";

function loads(text) {
  try { Limiter.load(text); return true; } catch (e) { if (e instanceof LimiterError) return false; throw e; }
}

// the version 2 text for one stored dump, or null when it already is one; throws when it is neither
function convert(text) {
  if (loads(text)) return null;
  const parts = text.split("|");
  if (parts[0] !== "tally/1" || parts.length < 2) throw new Error("neither a version 1 nor a version 2 dump");
  const v2 = ["tally/2", parts[1], "", ...parts.slice(2)].join("|");
  if (!loads(v2)) throw new Error("a version 1 dump that does not load");   // load checks what version 1's load checked
  return Limiter.load(v2).dump();
}

const i = process.argv.indexOf("--state");
const dir = i > 0 ? process.argv[i + 1] : undefined;
if (!dir || !statSync(dir, { throwIfNoEntry: false })?.isDirectory()) {
  process.stderr.write(`refused: --state ${dir} is not a directory\n`); process.exit(2);
}
const out = new Map(), problems = [], leftovers = [];
for (const name of readdirSync(dir).sort()) {
  const p = join(dir, name);
  const isFile = statSync(p).isFile();
  if (isFile && name.startsWith(".") && name.endsWith(".dump.migrating")) { leftovers.push(p); continue; }   // an interrupted run's copy
  if (!isFile || !name.endsWith(".dump")) { problems.push(`${name}: not a stored dump (<name>.dump)`); continue; }
  try {
    const v2 = convert(readFileSync(p, "utf8"));
    if (v2 !== null) out.set(p, v2);
  } catch (e) { problems.push(`${name}: ${e.message}`); }
}
if (problems.length) { process.stderr.write(`refused, nothing written:\n  ${problems.join("\n  ")}\n`); process.exit(1); }
for (const p of leftovers) unlinkSync(p);
for (const [p, text] of out) {                       // each file replaced whole: a crash leaves it old or new
  const tmp = join(dir, `.${p.split("/").pop()}.migrating`);
  writeFileSync(tmp, text); renameSync(tmp, p);
}
process.stdout.write(`converted ${out.size} version 1 dump(s)\n`);
