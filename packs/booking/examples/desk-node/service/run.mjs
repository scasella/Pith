// service/run.mjs — the entrypoint the judge starts (harness/SERVICE.md): node service/run.mjs --port P --db PATH.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Store, InvalidRequest, ConflictingReplay, Duplicate, Unknown } from "../profiles/node/store.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const arg = (name) => process.argv[process.argv.indexOf(`--${name}`) + 1];
const manifest = fs.readFileSync(path.join(ROOT, "app.manifest.yaml"), "utf8");
const UI = path.join(ROOT, (manifest.match(/^ui_entry:\s*(\S+)/m) || [])[1] || "ui/index.html");
const store = new Store(arg("db"));

function send(res, code, body, type = "application/json") {
  const data = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  res.writeHead(code, { "Content-Type": type, "Content-Length": data.length }); res.end(data);
}
function readJson(req) {
  return new Promise((resolve) => { let b = ""; req.on("data", (d) => (b += d)); req.on("end", () => resolve(b)); });
}
function route(method, url, body) {
  const [p, q = ""] = url.split("?"); let m;
  if (method === "GET") {
    if (p === "/") return [200, fs.readFileSync(UI), "text/html; charset=utf-8"];
    if (p === "/resources") return [200, { resources: store.resources() }];
    if ((m = p.match(/^\/resources\/(\d+)$/))) { const r = store.resource(Number(m[1])); return r ? [200, r] : [404, { error: "unknown resource" }]; }
    if ((m = p.match(/^\/bookings\/(\d+)$/))) { const b = store.booking(Number(m[1])); return b ? [200, b] : [404, { error: "unknown booking" }]; }
    if (p === "/events") return [200, store.eventsSince(Number((q.match(/since=(\d+)/) || [0, 0])[1]))];
    return [404, { error: "not found" }];
  }
  let b;
  try { b = JSON.parse(body || "null"); } catch { throw new InvalidRequest("body is not JSON"); }
  if (b === null || typeof b !== "object" || Array.isArray(b)) throw new InvalidRequest("body must be a JSON object");
  if (p === "/resources") return [201, store.createResource(b.id, b.name)];
  if ((m = p.match(/^\/resources\/(\d+)\/bookings$/))) return [200, store.book(b.request_id, Number(m[1]), b.start, b.end)];
  if ((m = p.match(/^\/bookings\/(\d+)\/cancel$/))) return [200, store.cancel(b.request_id, Number(m[1]))];
  if ((m = p.match(/^\/bookings\/(\d+)\/reschedule$/))) return [200, store.reschedule(b.request_id, Number(m[1]), b.start, b.end)];
  return [404, { error: "not found" }];
}
const server = http.createServer(async (req, res) => {
  const body = req.method === "POST" ? await readJson(req) : "";
  try { send(res, ...route(req.method, req.url, body)); }
  catch (e) {
    if (e instanceof ConflictingReplay || e instanceof Duplicate) return send(res, 409, { error: e.message });
    if (e instanceof Unknown) return send(res, 404, { error: e.message });
    if (e instanceof InvalidRequest) return send(res, 400, { error: e.message });
    send(res, 500, { error: String(e) });
  }
});
server.listen(Number(arg("port")), "127.0.0.1", () => console.log(`front desk on http://127.0.0.1:${arg("port")}`));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
