"""service/migrate.py — upgrade tally/v1 state to tally/v2 in place (harness/SERVICE.md, Upgrading from version 1;
migrations/from-1.yaml).

    python -I service/migrate.py --db <path>

- v2 state (meta.schema_version = 2): nothing to do, exit 0 (so a second run changes nothing).
- v1 state: every recorded v1 result becomes a result of counter "default" with the same request_id, outcome and tally;
  counter "default"'s tally is version 1's tally. The new database is written beside the old one, fsynced, and moved
  over it atomically; the v1 database is kept as <path>.v1 for forward repair.
- anything else: exit 2, nothing changed.

The version 1 state format is not part of this release's frozen contract, so v1 is recognised by content: a SQLite
database holding a results table (a request id column and an outcome column, optionally a tally column or a JSON
response column), or a JSON / JSON-lines file of such records. Version 1's tally is a stored tally if one is found and
consistent, otherwise the number of OK results (T2: the tally equals the accepted requests).
"""
import argparse, json, os, shutil, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store


class Unrecognised(Exception): pass


def fsync_dir(d):
    fd = os.open(d, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def norm_outcome(o):
    if isinstance(o, str) and o.upper() in ("OK", "REFUSED"): return o.upper()
    raise Unrecognised(f"outcome {o!r}")


def norm_id(r):
    if isinstance(r, str) and r.isdigit(): r = int(r)
    if type(r) is not int or not 0 <= r < 2 ** 53: raise Unrecognised(f"request id {r!r}")
    return r


def from_records(recs):
    """recs: iterable of dicts with request_id/outcome and maybe tally -> {rq: (outcome, tally or None)}."""
    out = {}
    for d in recs:
        if not isinstance(d, dict): raise Unrecognised("record is not an object")
        rq = d.get("request_id", d.get("id", d.get("rq")))
        out[norm_id(rq)] = (norm_outcome(d.get("outcome", d.get("result"))), d.get("tally"))
    return out


ID_COLS = ("request_id", "rq", "id", "req_id", "request")
OUT_COLS = ("outcome", "result", "status")
JSON_COLS = ("response", "body", "result_json", "answer", "json", "value")


def read_sqlite(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        results, stored = None, None
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            lc = {c.lower(): c for c in cols}
            idc = next((lc[c] for c in ID_COLS if c in lc), None)
            outc = next((lc[c] for c in OUT_COLS if c in lc), None)
            jsc = next((lc[c] for c in JSON_COLS if c in lc), None)
            if idc and (outc or jsc) and results is None:
                recs = []
                for row in con.execute(f'SELECT * FROM "{t}"'):
                    d = dict(zip(cols, row))
                    rec = {}
                    if jsc and isinstance(d[jsc], (str, bytes)):
                        try: j = json.loads(d[jsc])
                        except ValueError: j = None
                        if isinstance(j, dict): rec.update(j)
                    rec["request_id"] = d[idc]
                    if outc: rec["outcome"] = d[outc]
                    if "tally" in lc and d[lc["tally"]] is not None: rec["tally"] = d[lc["tally"]]
                    recs.append(rec)
                results = from_records(recs)
            elif "tally" in lc and not idc:
                rows = con.execute(f'SELECT "{lc["tally"]}" FROM "{t}"').fetchall()
                if len(rows) == 1 and type(rows[0][0]) is int: stored = rows[0][0]
            elif {"key", "value"} <= set(lc):
                for k, v in con.execute(f'SELECT "{lc["key"]}", "{lc["value"]}" FROM "{t}"'):
                    if k == "tally":
                        try: stored = int(v)
                        except (TypeError, ValueError): pass
        if results is None:
            if tables: raise Unrecognised(f"no results table among {tables}")
            results = {}
        return results, stored
    finally:
        con.close()


def read_json(path):
    text = open(path, "rb").read().decode("utf-8")
    try:
        doc = json.loads(text)
        lines = None
    except ValueError:
        doc = None
        try: lines = [json.loads(l) for l in text.splitlines() if l.strip()]
        except ValueError: raise Unrecognised("neither SQLite, JSON nor JSON lines")
    stored = None
    if lines is not None: recs = lines
    elif isinstance(doc, dict):
        stored = doc.get("tally") if type(doc.get("tally")) is int else None
        res = doc.get("results", doc.get("requests"))
        if isinstance(res, dict): recs = [dict(v, request_id=k) if isinstance(v, dict) else None for k, v in res.items()]
        elif isinstance(res, list): recs = res
        else: raise Unrecognised("JSON object without results")
    elif isinstance(doc, list): recs = doc
    else: raise Unrecognised("unexpected JSON")
    return from_records(recs), stored


def is_sqlite(path):
    with open(path, "rb") as f: return f.read(16) == b"SQLite format 3\x00"


def v2_version(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try: return store.schema_version(con)
    finally: con.close()


def build_v2(results, stored):
    ok = sum(o == "OK" for o, _ in results.values())
    tally = stored if stored is not None else ok
    if tally != ok or not 0 <= tally <= store.BOUND:
        raise Unrecognised(f"inconsistent version 1 state: tally {tally}, {ok} accepted results, bound {store.BOUND}")
    rows, running = [], 0
    for rq in sorted(results):                      # fill a missing per-result tally in request order (best effort)
        o, t = results[rq]
        if o == "OK": running += 1
        rows.append((rq, store.DEFAULT, o, t if type(t) is int else running))
    return rows, tally


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    path = os.path.abspath(a.db); d = os.path.dirname(path)
    if not os.path.isfile(path): sys.exit(f"refused: {path} does not exist; nothing to migrate")
    try:
        if is_sqlite(path):
            v = v2_version(path)
            if v == store.SCHEMA_VERSION: print("already tally/v2 state; nothing changed"); return
            if v is not None: raise Unrecognised(f"schema version {v!r}")
            results, stored = read_sqlite(path)
        else:
            results, stored = read_json(path)
        rows, tally = build_v2(results, stored)
    except Unrecognised as e:
        print(f"refused: {path} is not recognised tally/v1 or tally/v2 state ({e}); nothing changed", file=sys.stderr); sys.exit(2)
    except (sqlite3.DatabaseError, UnicodeDecodeError, OSError) as e:
        print(f"refused: {path} is not recognised tally/v1 or tally/v2 state ({e}); nothing changed", file=sys.stderr); sys.exit(2)

    tmp = path + ".v2-migrating"
    for p in (tmp, tmp + "-journal"):
        if os.path.exists(p): os.remove(p)
    con = store.connect(tmp); store.init(con)
    con.execute("BEGIN IMMEDIATE")
    con.executemany("INSERT INTO results(request_id, counter, outcome, tally) VALUES (?, ?, ?, ?)", rows)
    if tally: con.execute("INSERT INTO counters(name, tally) VALUES (?, ?)", (store.DEFAULT, tally))
    con.execute("COMMIT"); con.close()
    with open(tmp, "rb") as f: os.fsync(f.fileno())
    if not os.path.exists(path + ".v1"): shutil.copy2(path, path + ".v1")
    for side in ("-wal", "-shm"):                   # v1 sidecars were already read through the connection above
        if os.path.exists(path + side): shutil.copy2(path + side, path + ".v1" + side)
    fsync_dir(d)
    os.replace(tmp, path)
    for side in ("-wal", "-shm", "-journal"):
        if os.path.exists(path + side): os.remove(path + side)
    fsync_dir(d)
    print(f"migrated tally/v1 -> tally/v2: {len(rows)} results, counter default tally {tally}")


if __name__ == "__main__":
    main()
