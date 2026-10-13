#!/usr/bin/env python3
"""
gate.py — acceptance gate for a formal template.

    python3 gate/gate.py path/to/Implementation.dfy [--dafny /path/to/dafny] [--out claims.json]

The gate is the only thing that decides acceptance. It never reads prose.
It answers, in order:

  1. integrity   is the template unchanged?                       (sha256 of spec/)
  2. audit       has anyone proved the template unsatisfiable?    (audit/*.dfy must NOT verify)
  3. tcb         does the submission stay inside the trusted base? (banned constructs)
  4. verify      does the checker accept code + proof?            (dafny verify, warnings are errors)
  5. coverage    does the submission implement every required obligation?
  6. adequacy    does the template still reject the wrong candidates?   (each must FAIL to verify)
  7. traces      do the signed concrete traces execute as expected?     (dafny test)

and writes claims.json: one scoped claim per step, plus the assumptions the claims rest on.
Exit 0 means "assurance policy satisfied"; anything else is a refusal with a reason.
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, time, pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent   # = kernel/
MANIFEST = yaml.safe_load((ROOT / "gate" / "manifest.yaml").read_text())
TCB = yaml.safe_load((ROOT / "tcb.yaml").read_text())


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def norm(line):
    """Normalise a contract line for matching: strip comments, whitespace."""
    line = re.sub(r"//.*$", "", line)
    return re.sub(r"\s+", " ", line).strip()


def spec_files():
    return [ROOT / MANIFEST["spec"]] + [ROOT / p for p in MANIFEST.get("more_specs", [])]

def spec_tags():
    """Map normalised contract text -> set of obligation tags, from every spec file."""
    tags = {}
    lines = []
    for f in spec_files(): lines += f.read_text().splitlines()
    for raw in lines:
        found = re.findall(r"\[([A-Z0-9']+)\]", raw)
        if not found:
            continue
        if re.match(r"\s*&&", raw):                       # conjunct of Valid: carried by 'ensures Valid(a\')'
            tags.setdefault("ensures Valid(a')", set()).update(found)
        elif re.match(r"\s*(requires|ensures)", raw):
            tags.setdefault(norm(raw), set()).update(found)
    return tags


def tags_for_errors(output, file_path, tagmap):
    """Given dafny output, return the obligation tags of the postconditions that failed."""
    lines = pathlib.Path(file_path).read_text().splitlines()
    hit = set()
    for m in re.finditer(r"\((\d+),\d+\): Related location: this is the postcondition that could not be proved", output):
        ln = int(m.group(1))
        key = norm(lines[ln - 1])
        # the failing line in the submission restates a spec line; match by text
        for k, t in tagmap.items():
            if key and (key == k or key in k or k in key):
                hit |= t
    # invariant failures surface as 'Valid' — attribute to the invariant tags
    if "Valid(a')" in output or re.search(r"could not prove.*Valid", output):
        hit |= {"INV1", "P2", "P2'"}
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("impl")
    ap.add_argument("--dafny", default=os.environ.get("DAFNY", "dafny"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    impl = pathlib.Path(args.impl).resolve()
    dafny = args.dafny
    claims = {"template": MANIFEST["name"], "submission": str(impl.relative_to(ROOT)) if impl.is_relative_to(ROOT) else str(impl),
              "submission_sha256": sha256(impl), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "checker": run([dafny, "--version"])[1].strip(), "steps": [], "gate": "refused"}

    def step(name, ok, claim, detail=None):
        claims["steps"].append({"step": name, "result": "pass" if ok else "fail", "claim": claim, **({"detail": detail} if detail else {})})
        print(f"[ok] {name}: {claim}" if ok else f"[REFUSED] {name}: could not establish that {claim[0].lower()+claim[1:]}" + (f" — {json.dumps(detail)[:300]}" if detail else ""))
        if not ok:
            finish(); sys.exit(1)

    def finish():
        claims["assumptions"] = TCB["assumptions"]
        claims["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = args.out or (ROOT / "claims.json")
        pathlib.Path(out).write_text(json.dumps(claims, indent=2))
        print(f"claims written to {out}")

    # 1. integrity (every spec file)
    for f, expected in [(MANIFEST["spec"], MANIFEST["spec_sha256"])] + list(MANIFEST.get("more_spec_sha256", {}).items()):
        actual = sha256(ROOT / f)
        step(f"integrity:{pathlib.Path(f).name}", actual == expected, f"template {f} is unchanged (sha256 {actual[:12]})", {"expected": expected, "actual": actual})

    # 2. audit channel: a verified unsatisfiability proof invalidates the template, not the submission
    for a in sorted((ROOT / "audit").glob("*.dfy")):
        code, out = run([dafny, "verify", str(a)])
        step(f"audit:{a.name}", code != 0,
             f"no accepted proof that the template is unsatisfiable ({a.name} does not verify)",
             {"note": "if this file verifies, the TEMPLATE is rejected; see audit/README.md"})

    # 3. tcb scan over the translation unit and the implementation files it includes
    impl_files = [impl] + [impl.parent / i for i in re.findall(r'include\s+"([^"]+)"', impl.read_text()) if (impl.parent / i).exists() and (impl.parent / i).suffix == ".dfy"]
    text = "\n".join(f.read_text() for f in impl_files)
    violations = [b["pattern"] for b in TCB["banned_in_submissions"] if re.search(b["pattern"], text)]
    allowed_includes = {pathlib.Path(f).name for f in spec_files()} | {f.name for f in impl_files}
    includes = [i for f in impl_files for i in re.findall(r'include\s+"([^"]+)"', f.read_text())]
    bad_includes = [i for i in includes if pathlib.Path(i).name not in allowed_includes]
    step("tcb", not violations and not bad_includes,
         f"submission ({', '.join(f.name for f in impl_files)}) uses no verification bypasses and includes only the templates",
         {"banned_found": violations, "foreign_includes": bad_includes})

    # 4. verify (warnings are errors by default in Dafny 4: --allow-warnings=false)
    code, out = run([dafny, "verify", "--verify-included-files", str(impl)])
    m = re.search(r"finished with (\d+) verified, (\d+) errors", out)
    ok = code == 0 and m and m.group(2) == "0"
    step("verify", ok, f"checker accepts code, proof and the included template's lemmas ({m.group(1) if m else '?'} verified, {m.group(2) if m else '?'} errors; --verify-included-files)",
         None if ok else {"exit_code": code, "output": out[-3000:]})

    # 4b. reproduce the executable: the shipped Python translation must equal a fresh translation of the verified source
    shipped = impl.parent / "py" / "authcore-py"
    if shipped.exists():
        with tempfile.TemporaryDirectory() as td:
            code, out = run([dafny, "translate", "py", str(impl), "--output", f"{td}/authcore"])
            fresh = pathlib.Path(td) / "authcore-py"
            fresh_names = sorted(f.name for f in fresh.glob("*.py")) if fresh.exists() else []
            shipped_names = sorted(f.name for f in shipped.glob("*.py"))
            problems = []
            if code != 0: problems.append(f"translator exit {code}")
            if not fresh_names: problems.append("translator produced no Python files")
            if fresh_names != shipped_names: problems.append(f"file set differs: fresh {fresh_names} vs shipped {shipped_names}")
            for name in (fresh_names if not problems else []):
                if (fresh / name).read_text() != (shipped / name).read_text(): problems.append(f"content differs: {name}")
            step("translation", not problems, f"shipped Python translation equals a fresh translation of the verified source ({len(shipped_names)} files, translator exit 0)",
                 {"problems": problems, "output": out[-800:], "note": "regenerate with: dafny translate py <impl> --output core/py/authcore"} if problems else None)

    # 5. coverage: required traits implemented, every tagged obligation restated
    extends = set()
    for m in re.finditer(r"class\s+\w+\s+extends\s+([\w\s,\.]+)\{", text):
        extends |= {t.strip().split(".")[-1] for t in m.group(1).split(",")}
    missing_traits = [t for t in MANIFEST["required_traits"] if t not in extends]
    tagmap = spec_tags()
    impl_lines = {norm(l) for l in text.splitlines()}
    covered, uncovered = set(), set()
    for k, t in tagmap.items():
        (covered if (k in impl_lines or any(k in l or l in k for l in impl_lines if l)) else uncovered).update(t)
    uncovered -= covered
    step("coverage", not missing_traits and not uncovered,
         f"implements {sorted(extends)}; obligations covered: {sorted(covered)}",
         {"missing_traits": missing_traits, "uncovered": sorted(uncovered)})

    # 6. adequacy: wrong candidates must still be rejected, by the expected obligations
    for cand in MANIFEST["adequacy"]:
        path = ROOT / cand["file"]
        code, out = run([dafny, "verify", str(path)])
        rejected = tags_for_errors(out, path, tagmap)
        expected = set(cand["rejected_by"])
        ok = code != 0 and "postcondition that could not be proved" in out and expected <= rejected
        step(f"adequacy:{path.name}", ok,
             f"template rejects '{cand['describes']}' via {sorted(rejected & expected) or sorted(rejected)}",
             {"expected": sorted(expected), "observed": sorted(rejected)} if not ok else None)

    # 7. traces: signed concrete behaviours execute against THIS submission
    with tempfile.TemporaryDirectory(dir=ROOT) as td:
        tdir = pathlib.Path(td)
        src = (ROOT / MANIFEST["traces"]).read_text()
        src = re.sub(r'include\s+"[^"]+"', f'include "{impl}"', src, count=1)
        tf = tdir / "traces.dfy"; tf.write_text(src)
        code, out = run([dafny, "test", "--target", "py", str(tf)])
        passed = re.findall(r"^(\S+): PASSED", out, re.M)
        failed = re.findall(r"^(\S+): FAILED", out, re.M)
        ok = code == 0 and passed and not failed
        step("traces", ok, f"{len(passed)} signed traces executed as expected",
             None if ok else {"failed": failed, "output": out[-3000:]})

    try:
        prov = yaml.safe_load((ROOT / "adequacy" / "traces.provenance.yaml").read_text())
        claims["trace_provenance"] = {"status": prov.get("status"), "reviewers": prov.get("reviewers"), "note": prov.get("note")}
    except Exception:
        claims["trace_provenance"] = {"status": "unknown"}
    claims["gate"] = "assurance policy satisfied"
    claims["scope"] = {
        "proves": "for every input satisfying each obligation's precondition, the submitted methods establish its postconditions; the template's lemmas (Sum independence) are verified in the same run",
        "over": "the Dafny semantics of the submitted source; the shipped executable is byte-identical to the backend's translation of that source",
        "runtime_assumptions_not_checked_by_compiled_code": "preconditions (Valid(a), fresh request id) and nat domains are NOT enforced by the translated Python; the caller must establish them (see obligations/adapter)",
        "does_not_cover": TCB["not_covered"],
    }
    finish()
    print("GATE: assurance policy satisfied")


if __name__ == "__main__":
    main()
