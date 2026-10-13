# Handbook

A small internal handbook: pages written in a light Markdown, a search box, and a review step before a page's
policy text is published. It existed before Pith; this copy shows it **after** adopting the `pith.approval` pack for
one workflow, the review of policy documents (`handbook/reviews.py`).

```
handbook/      the project's code: db.py (one SQLite database), pages.py, search.py, web.py (the site), reviews.py
tests/         the project's own tests (Pith does not run them)
service/ cli/  added for the adoption: thin entrypoints exposing handbook/reviews.py through the pack's service and
               CLI contracts (harness/SERVICE.md, delivery/CLI-CONTRACT.md)
app.manifest.yaml, PITH.md   the adoption: what is included, which subsystem is covered, the record of what changed
```

Run the site: `python3 -m handbook.web --port 8080 --db handbook.db`. Run the project's tests: `python3 -m pytest tests`.

What Pith covers here is the review workflow, judged through `service/` and `cli/`: nothing about pages, search or
the site. See `PITH.md`.
