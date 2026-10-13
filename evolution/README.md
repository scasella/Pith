# evolution/

The safe-evolution demonstrations of v0.10.0 (`docs/rfc/0004-safe-evolution.md`, roadmap M5), run by
`validation/evolution.py` in CI. Two releases of one small contract, kept small so every demonstration runs in a few
minutes:

- `tally-v1/` — `demo.tally` 1.0.0, made by `python3 gate/cli.py pack new tally` and left as the scaffold made it: one
  bounded tally with idempotent requests.
- `tally-v2/` — `demo.tally` 2.0.0, a behavioral change: one bound per named counter (T1, T2 version 2), Idempotency
  and Durability unchanged, and M1, the upgrade of a running version 1 service with its state
  (`migrations/from-1.yaml`, forward-only). Examples: `basic` (SQLite; its migration adds a column), `journal` (the
  same application rewritten on an append-only journal; its migration converts the database), a known-wrong
  application (`wrong/default-bound`) and two known-wrong migrations (`wrong-migrations/`) that pass the ordinary judge
  and fail only when judged on populated state.

What `validation/evolution.py OUT` shows, each step recorded in `OUT/evolution-record.json`:

1. **agent handoff** — B plans a change from A's evidence (`gate/change.py plan`), makes it, classifies it, and is
   judged with A's evidence offered: only what the change left intact is reused;
2. **substantial rewrite** — the journal rewrite: integration route, every service-derived record invalidated, only the
   model checks carry over;
3. **contract upgrade with populated state** — v1 → v2 is behavioral, no v1 evidence holds or is reused, the v1
   deployment record does not cover the v2 artifact, both v2 applications migrate state the accepted v1 artifact
   produced (`gate/migrate.py`), and the known-wrong migrations are refused for their defect;
4. **composed workflow** — `gate/compose.py check compositions/ledger-receipts`.

These are scripted: the "agents" are scripted edits. Measuring real agents is the experiment harness's job (M6).
