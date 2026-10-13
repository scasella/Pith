"""The handbook's own tests (pages and search). Pith does not run these; they are the project's."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from handbook.db import Database
from handbook.pages import Pages, render
from handbook.search import search


def test_pages_round_trip_and_render(tmp_path):
    p = Pages(Database(str(tmp_path / "h.db"))); p.put("leave", "Leave policy", "# Leave\n\nTake **all** of it.")
    assert p.get("leave")["title"] == "Leave policy" and "<strong>all</strong>" in render(p.get("leave")["text"])


def test_search_ranks_by_occurrences(tmp_path):
    p = Pages(Database(str(tmp_path / "h.db"))); p.put("a", "Travel", "travel travel"); p.put("b", "Expenses", "travel once")
    assert [h["slug"] for h in search(p, "travel")] == ["a", "b"]
