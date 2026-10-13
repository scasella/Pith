// service/run.mjs — node service/run.mjs --port P --db PATH (harness/SERVICE.md). Node standard library only.
import http from "node:http";
import { Journal, Invalid, Conflict, Missing } from "./journal.mjs";

const arg = (n) => process.argv[process.argv.indexOf(`--${n}`) + 1];
const store = new Journal(arg("db") + ".journal");
const OPS = new Set(["edit", "submit", "approve", "reject", "publish"]);

function route(method, url, raw) {
  const [p, q = ""] = url.split("?"); let m;
  if (method === "GET") {
    if (p === "/actors") return [200, { actors: store.listActors() }];
    if (p === "/events") return [200, store.eventsSince(Number((q.match(/since=(\d+)/) || [0, 0])[1]))];
    if ((m = p.match(/^\/documents\/([^/]+)$/))) { const d = store.document(decodeURIComponent(m[1])); return d ? [200, d] : [404, { error: "unknown document" }]; }
    return [404, { error: "not found" }];
  }
  let b;
  try { b = JSON.parse(raw || "null"); } catch { throw new Invalid("body is not JSON"); }
  if (b === null || typeof b !== "object" || Array.isArray(b)) throw new Invalid("body must be a JSON object");
  if (p === "/actors") return [201, store.addActor(b.id, b.roles)];
  if (p === "/documents") return [200, store.create(b.request_id, b.id, b.actor, b.title, b.body)];
  if ((m = p.match(/^\/documents\/([^/]+)\/(\w+)$/)) && OPS.has(m[2])) return [200, store.command(m[2], b.request_id, decodeURIComponent(m[1]), b.actor, b.revision, b.body)];
  return [404, { error: "not found" }];
}

const server = http.createServer((req, res) => {
  let raw = ""; req.on("data", (d) => (raw += d));
  req.on("end", () => {
    let code, body;
    try { [code, body] = route(req.method, req.url, raw); }
    catch (e) {
      code = e instanceof Conflict ? 409 : e instanceof Missing ? 404 : e instanceof Invalid ? 400 : 500; body = { error: e.message };
    }
    const data = Buffer.from(JSON.stringify(body));
    res.writeHead(code, { "Content-Type": "application/json", "Content-Length": data.length }); res.end(data);
  });
});
server.listen(Number(arg("port")), "127.0.0.1", () => console.log(`change board on http://127.0.0.1:${arg("port")}`));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
