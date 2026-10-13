"""validation/evidence_reuse.py — dependency-aware evidence on real edits to a passing build.

    python3 validation/evidence_reuse.py <base-evidence-dir> <work-dir> [example]     (default example: examples/build-a)

<base-evidence-dir> is a run of the pristine gate on the example (validation/judge_example.sh). Then:
  1. a presentation edit (one comment appended to ui/index.html): `gate/evidence.py impact` must keep the proof, the
     design model checks and the generator checks, and invalidate delivery (and the checks that start the service);
  2. a design edit (one comment appended to design/Design.tla): the design checks are invalidated, the proof is not;
  3. the presentation edit judged with --reuse: exactly the cacheable records with unchanged keys are reused (the
     kernel proof and every TLC check), everything else runs again, and the statuses are those of the base run.
Exit 0 iff all three hold.
"""
import json, pathlib, shutil, subprocess, sys

SEED = pathlib.Path(__file__).resolve().parent.parent
base, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
example = SEED / (sys.argv[3] if len(sys.argv) > 3 else "examples/build-a")
work.mkdir(parents=True, exist_ok=True); bad = 0


def overlay(name, rel, line):
    d = work / name
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(example, d); p = d / rel; p.write_text(p.read_text() + line); return d


def impact(cand):
    r = subprocess.run([sys.executable, str(SEED / "gate/evidence.py"), "impact", "--evidence", str(base), "--candidate", str(cand), "--json"], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stdout + r.stderr)
    return {x["id"]: x for x in json.loads(r.stdout)}


def expect(label, rows, holds, invalid):
    global bad
    wrong = [i for i in holds if rows[i]["state"] != "holds"] + [i for i in invalid if rows[i]["state"] != "invalidated"]
    bad += bool(wrong)
    print(f"{'ok  ' if not wrong else 'FAIL'} {label}: holds {sorted(i for i, x in rows.items() if x['state'] == 'holds')}")
    print(f"       invalidated {sorted(i for i, x in rows.items() if x['state'] == 'invalidated')}")
    for i in wrong: print(f"       unexpected: {i} {rows[i]}")


B = json.loads((base / "evidence.json").read_text())
ids = [r["id"] for r in B["records"] if r.get("key")]
design = [i for i in ids if i.startswith("design.")]
tlc = [r["id"] for r in B["records"] if r.get("kind") == "tlc"]

ui = overlay("ui-edit", "ui/index.html", "\n<!-- presentation-only edit -->\n")
expect("presentation edit", impact(ui), holds=["kernel", *design, "gen.present", "gen.current", "monitor", "profile.tests"], invalid=["delivery", "lifecycle", "boundary", "approval"])
dz = overlay("design-edit", "design/Design.tla", "\n\\* a comment\n")
expect("design edit", impact(dz), holds=["kernel", "gen.present", "gen.current", "monitor", "profile.tests"], invalid=[*design])

out = work / "ev-ui-edit-reused"
if out.exists(): shutil.rmtree(out)
subprocess.run(["bash", str(SEED / "validation/judge_example.sh"), str(ui), str(out), "--reuse", str(base)], capture_output=True, text=True)
E = json.loads((out / "evidence.json").read_text())
reused = sorted(r["id"] for r in E["records"] if r.get("reused_from"))
want = sorted(["kernel", *tlc])
same = all(E["statuses"][s] == B["statuses"][s] for s in B["statuses"])
ok = reused == want and same
bad += not ok
print(f"{'ok  ' if ok else 'FAIL'} --reuse after the presentation edit: reused {reused}; statuses {'equal to the base run' if same else E['statuses']}")
if reused != want: print(f"       expected reused {want}")
sys.exit(1 if bad else 0)
