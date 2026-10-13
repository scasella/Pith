"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade this service's version 1 database at PATH to
version 2 in place (harness/SERVICE.md, "Upgrading from version 1"; service/store.py migrate): every resource gets
buffer 0, nothing else changes. Running it again changes nothing; anything else is refused (non-zero exit), untouched."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from service.store import migrate, Unrecognised


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    try: print(migrate(a.db))
    except Unrecognised as e: sys.exit(f"refused: {e}")


if __name__ == "__main__":
    main()
