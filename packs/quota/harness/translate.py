#!/usr/bin/env python3
"""harness/translate.py — reproduce the shipped Python translation of the verified core. FROZEN.

    DAFNY=dafny python3 harness/translate.py        -> harness/oracle-py/   (dafny translate py spec/QuotaCore.dfy)

The check oracle.translation (kind `regenerated`) runs this and requires the shipped files to be byte-identical to
what the translator produces now: the oracle the harnesses judge the candidate against is the verified core, not a
hand-edited copy. The Dafny Python runtime (`_dafny`) is the judge's DafnyRuntimePython package.
"""
import os, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
CORE = HERE.parent / "spec" / "QuotaCore.dfy"


def main():
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([os.environ.get("DAFNY", "dafny"), "translate", "py", str(CORE), "--output", f"{td}/oracle"], capture_output=True, text=True)
        if r.returncode != 0: sys.exit(f"dafny translate py failed:\n{r.stdout[-2000:]}{r.stderr[-2000:]}")
        dst = HERE / "oracle-py"
        shutil.rmtree(dst, ignore_errors=True); shutil.copytree(f"{td}/oracle-py", dst)


if __name__ == "__main__":
    main()
