#!/usr/bin/env python3
"""Ring-3 obligations, frozen. A syntax-and-structure lint plus reported semantic flags; it is NOT a semantic
evaluator and the gate labels it as such. Checks:
  1. ring-3 code (ui/, app/) never references the adapter, the core or storage directly
  2. app/SPEC.md exists, names every required workflow, and every sentence that claims a core behaviour cites an obligation
  3. the Human evaluation record table lists every required evaluation (informational: approval comes only from a signed attestation)
  4. semantic flags (reported, non-blocking): sentences pairing 'authorize' with 'exceed/over' or 'decline' with 'within/below'
Exit 0 with a JSON summary on stdout; exit 1 with [REFUSED] lines on structural failure."""
import re, sys, json, pathlib, yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
D = yaml.safe_load((ROOT / "obligations/app/delivery.yaml").read_text())
problems, flags = [], []

for p in [q for d in ("ui", "app") for q in (ROOT / d).rglob("*") if q.is_file() and q.suffix in {".html", ".js", ".py", ".ts", ".tsx"}]:
    t = p.read_text(errors="ignore")
    for bad in ["profiles.", "adapter", "AuthCore", "_dafny", "kernel/core", "sqlite", "import module_"]:
        if bad in t and p.name != "acceptance.py":
            problems.append(f"{p.relative_to(ROOT)}: references '{bad}' (ring 3 may only use the API)")

spec_path = ROOT / "app" / "SPEC.md"
if not spec_path.exists():
    print("[REFUSED] app/SPEC.md missing: copy obligations/app/SPEC.template.md and fill it in"); sys.exit(1)
spec = spec_path.read_text()

# requirement items (with continuation lines)
items, cur = [], None
for line in spec.splitlines():
    if re.match(r"\s*-\s*OC-\d+", line): cur = line.strip(); items.append(cur)
    elif cur is not None and line.startswith("  ") and line.strip(): items[-1] += " " + line.strip()
    else: cur = None
if not items: problems.append("SPEC.md has no requirement items (- OC-n ...)")
core_words = re.compile(r"\b(declin|authoriz|reserv|hold|limit|available|captur|post)", re.I)
TAG = r"\[(P0|P1|P2|P2'|P3|P4|INV1|R1|R2|C1|C2|C3|D|F)\]"
for it in items:
    if core_words.search(it) and not re.search(TAG, it) and "informal:" not in it:
        problems.append(f"SPEC.md: '{it[:70]}...' claims core behaviour without an obligation tag or informal: marker")
    if re.search(r"authori[sz]\w*\W+(?:\w+\W+){0,8}?(exceed|over the|above)", it, re.I) or re.search(r"declin\w*\W+(?:\w+\W+){0,8}?(within|below|under the)", it, re.I):
        flags.append(f"possible contradiction of P0/P1 wording: '{it[:90]}'")
for w in D["required_workflows"]:
    if w["id"] not in spec: problems.append(f"SPEC.md does not mention required workflow {w['id']} ({w['name']})")

# human evaluation record
rows = {}
for m in re.finditer(r"^\|\s*(E\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|", spec, re.M):
    rows[m.group(1)] = [x.strip() for x in m.groups()[1:]]
evals = {}
for e in D["required_evaluations"]:
    r = rows.get(e["id"])
    if r is None: problems.append(f"SPEC.md human evaluation record lacks a row for {e['id']} ({e['name']})"); continue
    by, date, result = r
    filled = by and by != "(pending)" and date and result
    evals[e["id"]] = ("rejected" if filled and result.lower().startswith(("fail", "reject")) else "approved" if filled else "pending")

if problems:
    print("\n".join("[REFUSED] " + p for p in problems)); sys.exit(1)
print(json.dumps({"items": len(items), "evaluations": evals, "flags": flags}))
