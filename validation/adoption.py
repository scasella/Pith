"""validation/adoption.py — the M4 existing-project journey, scripted from the published instructions (docs/ADOPTING.md):
take an existing project that has never seen Pith (packs/approval/examples/adopt-handbook without its Pith files), run
`gate/cli.py adopt`, judge it (refused: the entrypoints are missing, category evidence_missing), add the entrypoints
the adoption wrote, judge again (passes), and check that the evidence covers the included code and nothing else of the
project. Also: a project whose code sits in a directory named like a pack policy dir is refused by `adopt`, not
silently judged against the pack's copy. Writes <evidence-root>/adoption-record.json in the format an external
adopter's trial is recorded in (docs/ADOPTING.md § Recording a trial).

    python3 validation/adoption.py <evidence-root>
"""
import json, pathlib, shutil, subprocess, sys, tempfile, time

SEED = pathlib.Path(__file__).resolve().parent.parent
EX = SEED / "packs/approval/examples/adopt-handbook"
PITH_FILES = ["app.manifest.yaml", "PITH.md", "service", "cli"]
root = pathlib.Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
steps, bad = [], 0


def step(name, cmd, **kw):
    t = time.time(); r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    steps.append({"step": name, "command": " ".join(map(str, cmd)), "exit": r.returncode, "seconds": round(time.time() - t, 1)}); return r


def check(name, ok, detail=""):
    global bad
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else "")); bad += not ok


rel = pathlib.Path(tempfile.mkdtemp(prefix="rel-approval-")); shutil.rmtree(rel)
step("build the pristine release", [sys.executable, str(SEED / "gate/release.py"), "build", "--pack", str(SEED / "packs/approval"), "--out", str(rel)])
pin = subprocess.run([sys.executable, str(SEED / "gate/release.py"), "id", "--pack", str(SEED / "packs/approval")], capture_output=True, text=True).stdout.strip()
proj = pathlib.Path(tempfile.mkdtemp(prefix="handbook-"))
for p in EX.iterdir():
    if p.name not in PITH_FILES: (shutil.copytree if p.is_dir() else shutil.copy)(p, proj / p.name)

r = step("adopt", [sys.executable, str(SEED / "gate/cli.py"), "adopt", "--release", str(rel), "--project", str(proj), "--include", "handbook", "--name", "Handbook reviews",
                   "--subsystem", "review of policy documents (handbook/reviews.py), through service/ and cli/", "--json"])
a = json.loads(r.stdout)
check("adopt writes the manifest and the adoption record", r.returncode == 0 and (proj / "app.manifest.yaml").exists() and (proj / "PITH.md").exists(), str(a.get("problems")))
check("adopt names the entrypoints still to write", a.get("entrypoints_to_write") == ["cli/main.py", "service/run.py"], str(a.get("entrypoints_to_write")))


def judge(name):
    out = root / f"adopt-{name}"; shutil.rmtree(out, ignore_errors=True)
    step(f"judge ({name})", [sys.executable, "-I", str(rel / "gate/app_gate.py"), "--candidate", str(proj), "--out", str(out), "--expected-release", pin])
    return json.loads((out / "app-claims.json").read_text()), json.loads((out / "task-packet.json").read_text())


c, pk = judge("before-entrypoints")
f = pk["first_failure"] or {}
check("judged before the entrypoints exist: refused, evidence missing", c["behavioral_assurance"] == "refused" and f.get("category") == "evidence_missing", f"{f.get('check')} {f.get('category')}")
for d in ("service", "cli"): shutil.copytree(EX / d, proj / d)
c, pk = judge("adopted")
check("judged with the entrypoints: every status passed", all(str(c[s]).startswith("passed") for s in ("model_assurance", "behavioral_assurance", "application_delivery")) and pk["state"] == "done",
      " | ".join(f"{s}={str(c[s])[:8]}" for s in ("model_assurance", "behavioral_assurance", "application_delivery")))
cov = c.get("coverage") or {}
check("coverage names the included code and only the judged paths", cov.get("included") == ["handbook"] and cov.get("judged_paths") == ["app.manifest.yaml", "cli", "handbook", "service"], str(cov.get("judged_paths")))
check("the rest of the project is not in the judged artifact", not any((root / "adopt-adopted/artifact" / x).exists() for x in ("README.md", "tests", "PITH.md", "pyproject.toml")))

clash = pathlib.Path(tempfile.mkdtemp(prefix="clash-")); (clash / "model").mkdir(); (clash / "model/x.py").write_text("x = 1\n")
r = step("adopt (a project with a model/ directory)", [sys.executable, str(SEED / "gate/cli.py"), "adopt", "--release", str(rel), "--project", str(clash), "--subsystem", "x", "--include", "model", "--json"])
a = json.loads(r.stdout)
check("adopt refuses a project whose code sits in a pack policy dir", r.returncode == 1 and any("policy dirs" in p for p in a["problems"]) and not (clash / "app.manifest.yaml").exists(), str(a["problems"])[:160])

(root / "adoption-record.json").write_text(json.dumps({
    "format": "pith.adoption-trial/v1", "who": "validation/adoption.py (scripted; not an external developer)", "pack": "pith.approval", "release_digest": pin,
    "project": "packs/approval/examples/adopt-handbook", "journey": "existing-project", "instructions": "docs/ADOPTING.md",
    "steps": steps, "setup_failures": [], "interventions": [], "outcome": "accepted" if not bad else "not accepted"}, indent=1))
print(f"{'ok' if not bad else 'FAIL'}: existing-project adoption journey; record in {root / 'adoption-record.json'}")
sys.exit(1 if bad else 0)
