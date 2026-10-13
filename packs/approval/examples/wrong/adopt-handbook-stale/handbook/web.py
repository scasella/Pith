"""handbook/web.py — the handbook site: pages and search. Not part of the reviewed workflow; Pith does not judge it.

    python3 -m handbook.web --port 8080 --db handbook.db
"""
import argparse, html, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from handbook.db import Database
from handbook.pages import Pages, render
from handbook.search import search


def make(pages):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def page(self, code, title, body):
            data = f"<!doctype html><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1>{body}".encode()
            self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/":
                return self.page(200, "Handbook", "<ul>" + "".join(f'<li><a href="/pages/{p["slug"]}">{html.escape(p["title"])}</a>' for p in pages.all()) + "</ul>")
            if u.path.startswith("/pages/"):
                p = pages.get(u.path[len("/pages/"):])
                return self.page(200, p["title"], render(p["text"])) if p else self.page(404, "Not found", "")
            if u.path == "/search":
                q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
                return self.page(200, f"Search: {q}", "<ul>" + "".join(f'<li><a href="/pages/{h["slug"]}">{html.escape(h["title"])}</a>' for h in search(pages, q)) + "</ul>")
            self.page(404, "Not found", "")
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8080); ap.add_argument("--db", default="handbook.db"); a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), make(Pages(Database(a.db)))).serve_forever()
