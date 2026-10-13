"""handbook/pages.py — handbook pages: stored Markdown-ish text, rendered to HTML. Not part of the reviewed workflow."""
import html, re


class Pages:
    def __init__(self, db):
        self.db = db; db.schema("CREATE TABLE IF NOT EXISTS pages(slug TEXT PRIMARY KEY, title TEXT, text TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)")

    def put(self, slug, title, text):
        with self.db.transaction() as c:
            c.execute("INSERT INTO pages(slug, title, text) VALUES (?, ?, ?) ON CONFLICT(slug) DO UPDATE SET title=excluded.title, text=excluded.text, "
                      "updated=CURRENT_TIMESTAMP", (slug, title, text))

    def get(self, slug):
        r = self.db.query("SELECT slug, title, text FROM pages WHERE slug=?", slug)
        return dict(zip(("slug", "title", "text"), r[0])) if r else None

    def all(self): return [dict(zip(("slug", "title"), r)) for r in self.db.query("SELECT slug, title FROM pages ORDER BY title")]


def render(text):
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.match(r"(#{1,3}) (.*)", block)
        if m: out.append(f"<h{len(m[1])}>{html.escape(m[2])}</h{len(m[1])}>"); continue
        out.append("<p>" + re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(block)) + "</p>")
    return "\n".join(out)
