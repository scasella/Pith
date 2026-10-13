// service/migrate.mjs — node service/migrate.mjs --db PATH: upgrade a version 1 journal (approval-workflow/v1, kept at
// PATH.journal) to version 2 in place (harness/SERVICE.md, "Upgrading from version 1"). Every document gets quorum 2
// and keeps everything else; every recorded result is kept, its document carrying quorum 2, and every recorded
// create names quorum 2 (version 1's creates are creates with the default quorum, so their retries replay); actors
// and events are untouched. The new journal is written beside the old one, fsynced, then renamed over it, so an
// interrupted run leaves either journal whole. Running it again on a version 2 journal changes nothing; anything
// else is refused.
import fs from "node:fs";

const arg = (n) => process.argv[process.argv.indexOf(`--${n}`) + 1];
const path = arg("db") + ".journal";
const SCHEMA = JSON.stringify({ t: "schema", version: 2 });
const refuse = (why) => { console.error(`refused: ${why}`); process.exit(1); };

if (!fs.existsSync(path)) refuse(`${path} does not exist`);
let raw = fs.readFileSync(path, "utf8");
raw = raw.slice(0, raw.lastIndexOf("\n") + 1);                  // a torn last line (a crash mid-write) was never acknowledged
const lines = raw.split("\n").filter(Boolean);
if (lines[0] === SCHEMA) { console.log("already version 2: nothing to do"); process.exit(0); }

const withQuorum = (doc) => {
  if (doc == null) return doc;
  if ("quorum" in doc) refuse("a version 1 document already has a quorum");
  return { ...doc, quorum: 2 };
};
const out = [SCHEMA];
for (const line of lines) {
  let rec;
  try { rec = JSON.parse(line); } catch { refuse(`${path} is not a journal this service wrote`); }
  if (rec === null || typeof rec !== "object" || !Array.isArray(rec.events)) refuse(`unrecognised record ${line.slice(0, 80)}`);
  if (rec.t === "actor") out.push(line);
  else if (rec.t === "op") {
    const params = rec.params.op === "create" ? { ...rec.params, quorum: 2 } : rec.params;
    out.push(JSON.stringify({ ...rec, params, result: { ...rec.result, document: withQuorum(rec.result.document) }, doc: withQuorum(rec.doc) }));
  } else refuse(`unrecognised record type ${rec.t}`);
}
const tmp = path + ".v2";
const fd = fs.openSync(tmp, "w"); fs.writeSync(fd, out.join("\n") + "\n"); fs.fsyncSync(fd); fs.closeSync(fd);
fs.renameSync(tmp, path);
console.log(`migrated ${out.length - 1} version 1 journal records to version 2 (quorum 2)`);
