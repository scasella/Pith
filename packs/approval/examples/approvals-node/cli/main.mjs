#!/usr/bin/env node
// cli/main.mjs — the change board CLI (delivery/CLI-CONTRACT.md). Node standard library only; HTTP to the service.
import http from "node:http";
import { randomInt } from "node:crypto";
import { parseArgs } from "node:util";

const EXIT = { OK: 0, REFUSED: 3, UNKNOWN: 4, ERROR: 5 };
const COMMANDS = ["create", "edit", "submit", "approve", "reject", "publish", "show"];

function usage(msg) { process.stderr.write(`usage: main.mjs --server URL [--actor ID] [--request-id N] [--json] COMMAND DOC [--title T] [--body B] [--revision N]\nerror: ${msg}\n`); process.exit(2); }

function parse(argv) {
  let a;
  try {
    a = parseArgs({ args: argv, allowPositionals: true, options: {
      server: { type: "string" }, actor: { type: "string" }, "request-id": { type: "string" }, json: { type: "boolean" },
      title: { type: "string" }, body: { type: "string" }, revision: { type: "string" } } });
  } catch (e) { usage(e.message); }
  const o = a.values, [command, doc, ...rest] = a.positionals;
  if (!o.server) usage("--server is required");
  if (!COMMANDS.includes(command) || !doc || rest.length) usage("expected COMMAND DOC");
  const need = { create: ["actor", "title", "body"], edit: ["actor", "body"], show: [] }[command] ?? ["actor", "revision"];
  const missing = need.filter((n) => o[n] === undefined);
  if (missing.length) usage("missing " + missing.map((n) => "--" + n).join(", "));
  const num = (s, what) => { if (s === undefined) return undefined; if (!/^\d+$/.test(s)) usage(`${what} must be a non-negative integer`); return Number(s); };
  return { ...o, command, doc, revision: num(o.revision, "--revision"), requestId: num(o["request-id"], "--request-id") };
}

function call(server, method, path, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(path, server.replace(/\/$/, "") + "/");
    const data = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    const req = http.request(u, { method, timeout: 15000, headers: { "Content-Type": "application/json", ...(data ? { "Content-Length": data.length } : {}) } }, (res) => {
      let b = ""; res.on("data", (d) => (b += d));
      res.on("end", () => { let j = null; try { j = b ? JSON.parse(b) : null; } catch {} resolve([res.statusCode, j]); });
      res.on("error", reject);
    });
    req.on("timeout", () => req.destroy(new Error("timed out"))); req.on("error", reject);
    req.end(data);
  });
}

async function execute(a) {
  let rq = null, method = "POST", path, body;
  if (a.command === "show") { method = "GET"; path = `/documents/${encodeURIComponent(a.doc)}`; }
  else {
    rq = a.requestId ?? randomInt(2 ** 47) * 64 + randomInt(64);
    body = { request_id: rq, actor: a.actor };
    if (a.command === "create") { path = "/documents"; Object.assign(body, { id: a.doc, title: a.title, body: a.body }); }
    else if (a.command === "edit") { path = `/documents/${encodeURIComponent(a.doc)}/edit`; body.body = a.body; }
    else { path = `/documents/${encodeURIComponent(a.doc)}/${a.command}`; body.revision = a.revision; }
  }
  let status, r;
  try { [status, r] = await call(a.server, method, path, body); }
  catch (e) { return { outcome: "UNKNOWN", reason: `no answer from the service (${e.code || e.message})`, request_id: rq, replayed: null, document: null }; }
  if (status !== 200 || !r || typeof r !== "object")
    return { outcome: "ERROR", reason: `HTTP ${status}${r && r.error ? ": " + r.error : ""}`, request_id: rq, replayed: null, document: null };
  if (a.command === "show") return { outcome: "OK", reason: null, request_id: null, replayed: null, document: r };
  return { outcome: r.outcome, reason: r.reason, request_id: rq, replayed: r.replayed, document: r.document };
}

function forPerson(res) {
  const out = [res.outcome + (res.outcome === "REFUSED" ? ` ${res.reason}` : res.reason ? `: ${res.reason}` : "")];
  if (res.request_id !== null) out.push(`request ${res.request_id}${res.replayed ? " (replayed)" : ""}`);
  if (res.outcome === "UNKNOWN" && res.request_id !== null) out.push(`It may or may not have been applied. Retry safely with --request-id ${res.request_id}`);
  const d = res.document;
  if (d) out.push(`${d.id}: ${d.title}`, `status: ${d.status}`, `revision: ${d.revision}`, `votes on this revision: ${d.current_votes.join(", ") || "none"}`);
  return out.join("\n");
}

const a = parse(process.argv.slice(2));
const res = await execute(a);
process.stdout.write((a.json ? JSON.stringify(res) : forPerson(res)) + "\n");
process.exitCode = EXIT[res.outcome] ?? 5;
