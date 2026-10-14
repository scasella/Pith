"""service/store.py — the tally/v2 state: one SQLite file (the --db path), committed with synchronous=FULL before any
answer is sent. Schema version 2 is recorded in table meta."""
import sqlite3

SCHEMA_VERSION = "2"
BOUND = 3
DEFAULT = "default"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, tally INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS results (request_id INTEGER PRIMARY KEY, counter TEXT NOT NULL,
                                    outcome TEXT NOT NULL CHECK (outcome IN ('OK','REFUSED')), tally INTEGER NOT NULL);
"""


def connect(path):
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=30)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=FULL")
    return con


def init(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]: con.execute(stmt)
        con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK"); raise


def schema_version(con):
    try: row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError: return None
    return row[0] if row else None
