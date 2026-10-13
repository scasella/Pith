#!/usr/bin/env python3
"""harness/adequacy.py — a known-wrong core is rejected by the contract FOR THE REASON IT CLAIMS, and differs from
the verified core on a reviewed trace. FROZEN.

    DAFNY=dafny python3 harness/adequacy.py spec/wrong/<core>.dfy      the check core.adequacy (one per wrong core)
    python3 harness/adequacy.py --print                                 the reviewed traces, as Markdown, for a reviewer

A wrong core names, in its header, the obligations that must reject it (`// REJECTED-BY: [Q1] ...`) and the trace it
must get wrong (`// DIFFERS-ON: T1_...`). This script requires all three of:
  1. `dafny verify` fails, and every error is an unproved postcondition (a syntax, type or subset-constraint error
     would make the core "rejected" for a reason that says nothing about the contract);
  2. among the postconditions Dafny reports unproved, there is one tagged with each REJECTED-BY obligation;
  3. run against spec/TraceData.dfy (`dafny run --no-verify`), the core's decisions differ on the DIFFERS-ON trace:
     an unprovable postcondition is not the same as a violated one, and the trace is the concrete violation.
Why this is a script and not `kind: command` + `expect_exit: nonzero` (which booking uses): see AUTHORING-NOTES.md.
"""
import os, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
DAFNY = os.environ.get("DAFNY", "dafny")


def dafny(*args, cwd=ROOT):
    r = subprocess.run([DAFNY, *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def header(src, field):
    m = re.search(rf"^// {field}:(.*)$", src, re.M)
    return m.group(1).split() if m else []


def check(item):
    path = (ROOT / item).resolve(); src = path.read_text(); problems = []
    rejected_by = header(src, "REJECTED-BY"); differs_on = header(src, "DIFFERS-ON")
    if not rejected_by or not differs_on: return [f"{item}: header must name REJECTED-BY obligations and a DIFFERS-ON trace"]
    # 1 + 2: verification fails, only on postconditions, including one per claimed obligation
    code, out = dafny("verify", str(path))
    errors = re.findall(r"^\S+\(\d+,\d+\): Error: (.*)$", out, re.M)
    if code == 0: problems.append(f"{item} verified: the contract no longer rejects this core")
    other = sorted({e for e in errors if not e.startswith("a postcondition could not be proved")})
    if other or (code != 0 and not errors): problems.append(f"{item} is rejected for a reason other than the contract: {other or out[-600:]}")
    tags = set(re.findall(r"^\s*\d+ \|.*ensures.*//\s*(\[[A-Z0-9]+\])", out, re.M)) | set(re.findall(r"^\s*\d+ \|.*//\s*(\[[A-Z0-9]+\])\s*$", out, re.M))
    missing = [t for t in rejected_by if t not in tags]
    if missing: problems.append(f"{item}: no unproved postcondition tagged {missing} (unproved: {sorted(tags)})")
    # 3: the concrete trace differs
    with tempfile.TemporaryDirectory() as td:
        main = pathlib.Path(td) / "run_wrong.dfy"
        main.write_text(f'include "{path}"\ninclude "{SPEC / "TraceData.dfy"}"\n'
                        "module RunWrong {\n  import opened QuotaTraces\n  import Wrong\n"
                        "  method Main() {\n    var all := All(); var i := 0;\n    while i < |all| {\n"
                        "      var w := new Wrong.C(); var m := Run(w, all[i]);\n"
                        '      if m != -1 { print "DIFFERS ", all[i].name, " at step ", m, "\\n"; }\n'
                        "      i := i + 1;\n    }\n  }\n}\n")
        code, out = dafny("run", "--no-verify", "--target", "py", str(main), cwd=td)
    differs = set(re.findall(r"^DIFFERS (\S+) at step", out, re.M))
    if code != 0: problems.append(f"{item}: running the traces failed: {out[-600:]}")
    for t in differs_on:
        if t not in differs: problems.append(f"{item} gives the reviewed decisions on {t}: the trace does not tell it apart from the contract")
    if not problems: print(f"ok: {item} rejected by {' '.join(rejected_by)} (only unproved postconditions); differs on {', '.join(sorted(differs))}")
    return problems


def print_traces():
    src = (SPEC / "TraceData.dfy").read_text()
    for block in re.split(r"\n\s*// (?=T\d)", src)[1:]:
        lines = block.splitlines(); print(f"### {lines[0]}\n")
        m = re.search(r'Trace\("(\w+)", Config\((\d+), (\d+)\)', block)
        print(f"`{m.group(1)}` — limit {m.group(2)}, window {m.group(3)}\n\n| key | cost | now | the contract requires | why |\n|---|---|---|---|---|")
        for s in re.finditer(r'Step\("(\w+)", (\d+), (\d+), ([^)]*\)?)\)[,\s]*(?://\s*(.*))?', block):
            print(f"| {s.group(1)} | {s.group(2)} | {s.group(3)} | `{s.group(4)}` | {s.group(5) or ''} |")
        print()


if __name__ == "__main__":
    if sys.argv[1:] == ["--print"]: print_traces(); sys.exit(0)
    probs = [p for item in sys.argv[1:] for p in check(item)]
    print("\n".join(probs)); sys.exit(1 if probs else 0)
