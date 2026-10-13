"""handbook/db.py — one SQLite database for the whole handbook. Every write is one immediate transaction."""
import contextlib, sqlite3, threading


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL"); self.conn.execute("PRAGMA synchronous=FULL")
        self.lock = threading.RLock()

    @contextlib.contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try: yield self.conn; self.conn.execute("COMMIT")
            except BaseException: self.conn.execute("ROLLBACK"); raise

    def query(self, sql, *args):
        with self.lock: return self.conn.execute(sql, args).fetchall()

    def schema(self, *ddl):
        with self.lock:
            for d in ddl: self.conn.execute(d)
