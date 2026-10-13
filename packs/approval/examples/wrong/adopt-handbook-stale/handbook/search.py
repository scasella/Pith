"""handbook/search.py — naive full-text search over pages. Not part of the reviewed workflow."""
import re


def search(pages, query, limit=10):
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    if not words: return []
    hits = []
    for p in pages.all():
        text = (p["title"] + " " + (pages.get(p["slug"]) or {}).get("text", "")).lower()
        score = sum(text.count(w) for w in words)
        if score: hits.append((score, p["slug"], p["title"]))
    return [{"slug": s, "title": t, "score": n} for n, s, t in sorted(hits, key=lambda h: (-h[0], h[1]))[:limit]]
