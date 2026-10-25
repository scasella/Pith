"""profiles/sqlite_occ/migrate.py — put a database the shipped sqlite profile wrote into the layout profiles/sqlite_occ reads. FROZEN.
Candidates on this profile call it from their own entrypoint (service/migrate.py: `migrate(path)`).

  - a database in the layout profiles/sqlite writes (tables accounts(id, state), events, receipts, meta; schema 3): in one transaction,
    accounts gets `version` (every account at version 0) and the `occ` marker table is created; nothing else changes, so events,
    receipts and the hash chain are kept byte for byte
  - a database of the previous contract (accounts and events only): upgraded first by profiles/sqlite/migrate.py (receipts built
    from the log), then as above
  - a database already in this layout: left as it is (a second run changes nothing)
  - anything else: refused and left untouched
"""
import os, sqlite3
from profiles.sqlite import migrate as previous
from profiles.sqlite.repo import SCHEMA, TABLES as SQLITE_TABLES, tables
from .repo import TABLES, OCC_DDL, layout_current


class Refused(RuntimeError): pass


def migrate(path):
    """Upgrade the database at `path` in place. Returns a one-line summary; raises Refused (state untouched)."""
    if not os.path.isfile(path): raise Refused(f"{path} does not exist")
    note = ""
    try:
        db = sqlite3.connect(path, isolation_level=None); have = tables(db); db.close()
        if have == {"accounts", "events"}:                                   # the previous contract: receipts first
            try: note = previous.migrate(path) + "; "
            except previous.Refused as e: raise Refused(str(e))
    except sqlite3.DatabaseError as e: raise Refused(f"{path} is not a database this profile can read ({e})")
    db = sqlite3.connect(path, isolation_level=None)
    try:
        have = tables(db)
        if have == TABLES and layout_current(db, have): return "already in the sqlite-occ layout: nothing to do"
        if have != SQLITE_TABLES or db.execute("SELECT value FROM meta WHERE key='schema'").fetchone() != (SCHEMA,):
            raise Refused(f"unrecognised state (tables {sorted(have)}): not a database profiles/sqlite or profiles/sqlite_occ wrote for this contract")
        db.execute("BEGIN IMMEDIATE")
        db.execute("ALTER TABLE accounts ADD COLUMN version INTEGER NOT NULL DEFAULT 0"); db.execute(OCC_DDL); db.execute("INSERT INTO occ(layout) VALUES(1)")
        n = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        db.execute("COMMIT")
        return f"{note}migrated {n} account(s) to the sqlite-occ layout (version 0); events and receipts unchanged"
    finally: db.close()
