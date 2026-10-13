"""migrations/migrate.py --state DIR — run the candidate's migrate entrypoint for its runtime. FROZEN.

gate/migrate.py runs this as the candidate (migrations/from-v1.yaml `migrate`) in the new release's workspace. It
reads `runtime` from app.manifest.yaml (python by default, as the pack's preflight does) and replaces itself with
`python -I lib/migrate.py --state DIR` or `node lib/migrate.mjs --state DIR` (harness/LIBRARY.md, Upgrading from
version 1): the exit code is the entrypoint's. It reads the manifest without a YAML library because the candidate's
process has only the standard library.
"""
import os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
manifest = ROOT / "app.manifest.yaml"
m = re.search(r"^runtime:\s*['\"]?([A-Za-z]+)['\"]?\s*(#.*)?$", manifest.read_text(), re.M) if manifest.exists() else None
runtime = m.group(1) if m else "python"
entry = {"python": ("lib/migrate.py", [sys.executable, "-I"]), "node": ("lib/migrate.mjs", ["node"])}.get(runtime)
if entry is None: sys.exit(f"refused: runtime {runtime!r} is neither python nor node")
if not (ROOT / entry[0]).is_file(): sys.exit(f"refused: {entry[0]} is missing; this version upgrades version 1 state (harness/LIBRARY.md, Upgrading from version 1)")
os.chdir(ROOT)
argv = entry[1] + [entry[0]] + sys.argv[1:]
os.execvp(argv[0], argv)
