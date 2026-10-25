"""model/redteam_tlc.py — does the release's model accept a design? FROZEN once sealed. The pack's half of gate/redteam.py's
spec target (pack.yaml `redteam.spec`), and the adequacy check's way of running a known-wrong design.

    python3 model/redteam_tlc.py --design FILE [--property NAME] [--work DIR]

The design is checked in place of Spec.tla under MC.tla's constants: against MC.cfg's own invariants (the properties the
release actually checks), or, with --property, against that one property alone (a witness). Exit 0: no error found;
1: a property is violated; 3: TLC did not run or could not parse the design (never read as either verdict).
"""
import argparse, os, pathlib, re, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser(); ap.add_argument("--design", required=True); ap.add_argument("--property"); ap.add_argument("--work")
a = ap.parse_args()
work = pathlib.Path(a.work or tempfile.mkdtemp(prefix="redteam-tlc-")) / "tlc"
if work.exists(): shutil.rmtree(work)
work.mkdir(parents=True)
shutil.copy(HERE / "MC.tla", work / "MC.tla")
src = pathlib.Path(a.design).read_text()
(work / "Spec.tla").write_text(re.sub(r"^-{4,}\s*MODULE\s+\w+\s*-{4,}", "---- MODULE Spec ----", src, count=1, flags=re.M))
cfg = (HERE / "MC.cfg").read_text()
if a.property: cfg = re.sub(r"(?ms)^INVARIANTS?\b.*?(?=^\S|\Z)", "", cfg).rstrip() + f"\nINVARIANT {a.property}\n"
(work / "MC.cfg").write_text(cfg)
jar = os.environ.get("TLA2TOOLS", "tla2tools.jar")
try:
    r = subprocess.run(["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-nowarning", "-deadlock", "-config", "MC.cfg", "MC"],
                       cwd=work, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
except (OSError, subprocess.TimeoutExpired) as e:
    print(f"TLC did not run: {e}"); sys.exit(3)
print(out[-1500:])
if "No error has been found" in out: sys.exit(0)
if re.search(r"(Invariant|Action property|Temporal property) \S+ is violated", out): sys.exit(1)
sys.exit(3)
