"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade the state a version 1 service left at PATH to
version 2 in place (harness/SERVICE.md, "Upgrading from version 1"), with the shipped profile's migration: every
resource gets buffer 0 and every booking, recorded result and event is kept. Running it again changes nothing; state
it does not recognise is refused (non-zero exit) and left untouched."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from profiles.python.store import migrate, Unrecognised


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    try: print(migrate(a.db))
    except Unrecognised as e: sys.exit(f"refused: {e}")


if __name__ == "__main__":
    main()
