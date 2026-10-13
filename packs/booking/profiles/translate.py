#!/usr/bin/env python3
"""profiles/translate.py — reproduce the shipped translations of the verified core. FROZEN.

    DAFNY=dafny python3 profiles/translate.py py     -> profiles/python/bookingcore-py/   (dafny translate py)
    DAFNY=dafny python3 profiles/translate.py js     -> profiles/node/bookingcore.js      (dafny translate js --include-runtime + export footer)

The pack's checks `translation.python` and `translation.node` (kind `regenerated`) run this and require the shipped
files to be byte-identical to what the translator produces now: the shipped code is the verified core, not a
hand-edited copy. The JavaScript runtime needs bignumber.js, vendored (MIT) in profiles/node/node_modules/.
"""
import os, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
CORE = HERE.parent / "spec" / "BookingCore.dfy"
JS_FOOTER = "\n// --- appended by profiles/translate.py: CommonJS exports for profiles/node/store.mjs ---\nmodule.exports = { BookingSpec, BookingCore, _dafny, BigNumber };\n"


def dafny(*args):
    r = subprocess.run([os.environ.get("DAFNY", "dafny"), *args], capture_output=True, text=True)
    if r.returncode != 0: sys.exit(f"dafny {' '.join(args[:2])} failed:\n{r.stdout[-2000:]}{r.stderr[-2000:]}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    with tempfile.TemporaryDirectory() as td:
        if target == "py":
            dafny("translate", "py", str(CORE), "--output", f"{td}/bookingcore")
            dst = HERE / "python" / "bookingcore-py"
            shutil.rmtree(dst, ignore_errors=True); shutil.copytree(f"{td}/bookingcore-py", dst)
        elif target == "js":
            dafny("translate", "js", "--include-runtime", str(CORE), "--output", f"{td}/bookingcore")
            (HERE / "node" / "bookingcore.js").write_text(pathlib.Path(f"{td}/bookingcore.js").read_text() + JS_FOOTER)
        else:
            sys.exit("usage: translate.py py|js")


if __name__ == "__main__":
    main()
