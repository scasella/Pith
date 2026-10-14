"""migrations/migrate.py — python -I migrations/migrate.py --db PATH: run the candidate's own migrate entrypoint for the
runtime its app.manifest.yaml names (harness/SERVICE.md, "Upgrading from version 1"). FROZEN.

The release's migration spec (migrations/from-v1.yaml) has one `migrate` command; a candidate may run on Python or on
Node.js. This dispatcher only picks the entrypoint, it migrates nothing itself:

    runtime python   python -I service/migrate.py --db PATH
    runtime node     node service/migrate.mjs --db PATH

It is run by gate/migrate.py in the judged workspace, as the candidate, and exits with the entrypoint's exit code (2 if
the entrypoint is missing)."""
import argparse, os, pathlib, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRY = {"python": [sys.executable, "-I", "service/migrate.py"], "node": ["node", "service/migrate.mjs"]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    m = ROOT / "app.manifest.yaml"
    rt = ((yaml.safe_load(m.read_text()) or {}) if m.exists() else {}).get("runtime") or "python"
    if rt not in ENTRY: sys.exit(f"refused: runtime {rt!r} is not python or node")
    argv = ENTRY[rt] + ["--db", a.db]
    if not (ROOT / argv[-3]).is_file(): print(f"no migrate entrypoint: {argv[-3]} (harness/SERVICE.md, Upgrading from version 1)", file=sys.stderr); sys.exit(2)
    os.chdir(ROOT); sys.stdout.flush()
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
