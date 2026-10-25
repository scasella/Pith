"""validation/evidence_reuse.py — dependency-aware evidence on real edits to a passing build.

    python3 validation/evidence_reuse.py <base-evidence-dir> <work-dir> [example]     (default example: examples/build-a)

<base-evidence-dir> is a run of the pristine gate on the example (validation/judge_example.sh). Then:
  1. a presentation edit (one comment appended to ui/index.html): `gate/evidence.py impact` must keep the proof, the
     design model checks and the generator checks, and invalidate delivery (and the checks that start the service);
  2. a design edit (one comment appended to design/Design.tla): the design checks are invalidated, the proof is not;
  3. the presentation edit judged with --reuse: exactly the cacheable records with unchanged keys are reused (the
     kernel proof and every TLC check), everything else runs again, and the statuses are those of the base run;
  4. multi-source reuse (v0.13.0; what a fork-join merge relies on, RFC 0007 § 8): the design edit D judged with the base
     offered, then M = D plus the presentation edit judged (a) with only the base offered: the design model checks run
     again (their inputs differ from the base's) and only the kernel proof is reused; (b) with the base AND D offered:
     every cacheable record is reused, the design checks from D's evidence, the kernel proof from either, each record
     naming the evidence it came from, and the statuses are those of the base run.
Exit 0 iff all four hold.
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


# 4. multi-source reuse
def judge(cand, out, *offered):
    if out.exists(): shutil.rmtree(out)
    subprocess.run(["bash", str(SEED / "validation/judge_example.sh"), str(cand), str(out), *[x for o in offered for x in ("--reuse", str(o))]], capture_output=True, text=True)
    return json.loads((out / "evidence.json").read_text()) if (out / "evidence.json").is_file() else {"records": [], "statuses": {}, "digest": None}


def sources(E): return {r["id"]: (r["reused_from"] or {}).get("evidence_digest") for r in E["records"] if r.get("reused_from")}


D_ev = judge(dz, work / "ev-design-edit", base)
m = work / "design-and-ui-edit"
if m.exists(): shutil.rmtree(m)
shutil.copytree(dz, m); (m / "ui/index.html").write_text((m / "ui/index.html").read_text() + "\n<!-- presentation-only edit -->\n")
Ma = judge(m, work / "ev-m-base-only", base)
Mb = judge(m, work / "ev-m-base-and-design-edit", base, work / "ev-design-edit")
same_a, same_b = all(Ma["statuses"].get(s) == B["statuses"][s] for s in B["statuses"]), all(Mb["statuses"].get(s) == B["statuses"][s] for s in B["statuses"])
reused_a, reused_b = sorted(sources(Ma)), sorted(sources(Mb)); src_b = sources(Mb)
ok_a = bool(D_ev["digest"]) and "kernel" in reused_a and not set(reused_a) & set(design) and set(tlc) - set(design) <= set(reused_a) and same_a
ok_b = bool(D_ev["digest"]) and reused_b == want and same_b and all(src_b.get(i) == D_ev["digest"] for i in tlc if i in design) and all(d in (B["digest"], D_ev["digest"]) for d in src_b.values())
bad += not (ok_a and ok_b)
print(f"{'ok  ' if ok_a else 'FAIL'} multi-source reuse (a), only the base offered, after a design and a presentation edit: reused {reused_a}; the design checks run again; statuses {'equal to the base run' if same_a else Ma['statuses']}")
print(f"{'ok  ' if ok_b else 'FAIL'} multi-source reuse (b), the base and the design edit's evidence offered: reused {reused_b}; "
      f"from the design edit's evidence: {sorted(i for i, d in src_b.items() if d == D_ev['digest'])}, from the base's: {sorted(i for i, d in src_b.items() if d == B['digest'])}; statuses {'equal to the base run' if same_b else Mb['statuses']}")
if not ok_b: print(f"       expected reused {want}")
sys.exit(1 if bad else 0)
