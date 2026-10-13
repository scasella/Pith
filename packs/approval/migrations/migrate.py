"""migrations/migrate.py — the migrate command of migrations/from-v1.yaml. FROZEN. It decides nothing: it runs the
candidate's own migrate entrypoint for the runtime its app.manifest.yaml names (harness/SERVICE.md, "Upgrading from
version 1"), in the judged workspace, and exits with its exit code.

    python -I migrations/migrate.py --db PATH       ->  python -I service/migrate.py --db PATH   (runtime: python)
                                                    ->  node service/migrate.mjs --db PATH       (runtime: node)
"""
import argparse, os, pathlib, sys
import yaml

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
m = pathlib.Path("app.manifest.yaml")
runtime = ((yaml.safe_load(m.read_text()) or {}) if m.is_file() else {}).get("runtime") or "python"
argv = {"python": [sys.executable, "-I", "service/migrate.py"], "node": ["node", "service/migrate.mjs"]}.get(runtime)
if argv is None: sys.exit(f"refused: unknown runtime {runtime!r}")
if not pathlib.Path(argv[-1]).is_file(): sys.exit(f"{argv[-1]} missing: version 2 upgrades a running version 1 service (harness/SERVICE.md, Upgrading from version 1)")
sys.stdout.flush()
try: os.execvp(argv[0], argv + ["--db", a.db])
except OSError as e: sys.exit(f"cannot run {argv[0]}: {e}")
