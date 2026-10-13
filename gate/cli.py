#!/usr/bin/env python3
"""
gate/cli.py — the command-line and machine-readable interface to Pith. FROZEN. Domain-free.

One stable entry point for people, agents and wrappers (Spec Kit, CI, an agent harness). Every subcommand takes
--json and then prints exactly one JSON document on stdout (human text goes to stderr); exit codes are stable:
0 ok / done, 1 refused or not ok, 2 the completion status was not reached, 3 usage error.

    python3 gate/cli.py doctor   [--pack DIR] [--json]                 is this machine ready to judge the pack? what to install if not
    python3 gate/cli.py verify   [--json] -- <app_gate.py arguments>   judge, then print the task packet (TASK.md, or its JSON)
    python3 gate/cli.py packet   EVIDENCE_DIR [--json]                  the task packet of an earlier run
    python3 gate/cli.py pack new NAME --out DIR                        scaffold a draft pack (needs a Pith source checkout: templates/pack)
    python3 gate/cli.py pack check DIR [--release --reviews DIR --reviewer-key PUB ...] [--json]
                                                                       consistency and adequacy checks for a pack; with --release, also an
                                                                       independent signed review of this release (gate/review.py sign-pack)
    python3 gate/cli.py adopt    --release DIR --project DIR --subsystem TEXT [--include PATH ...] [--name NAME] [--json]
                                                                       add a pack to one workflow of an existing project (docs/ADOPTING.md)
    python3 gate/cli.py change   plan|classify ...                      what a change reaches and what it must re-establish (gate/change.py)
    python3 gate/cli.py compose  check DIR                              check a composition contract (gate/compose.py)
    python3 gate/cli.py migrate  run ...                                judge a migration on populated state (gate/migrate.py)
    python3 gate/cli.py deploy   record|check ...                       bind evidence to a deployment (gate/deploy.py)
    python3 gate/cli.py impact   impact|verify ...                      evidence invalidation (gate/evidence.py)
    python3 gate/cli.py catalog  check|revoked|pin ...                  the catalog of maintained packs, and revocations (gate/catalog.py)
      (these six pass their arguments through; with --json, where the tool takes it, stdout is one JSON document)

Agent-specific integrations should be thin wrappers over these commands (integrations/).
Format of the task packet: gate/schemas/task-packet.schema.json; categories: gate/packet.py.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, time
import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import workspace as W, pack as PK, packet as PT

EXIT_OK, EXIT_NOT_OK, EXIT_INCOMPLETE, EXIT_USAGE = 0, 1, 2, 3
DELEGATED = {"change": "change.py", "compose": "compose.py", "migrate": "migrate.py", "deploy": "deploy.py", "impact": "evidence.py", "catalog": "catalog.py"}


def emit(as_json, obj, text):
    if as_json: print(json.dumps(obj, indent=1))
    else: print(text)


# ---------------------------------------------------------------- doctor
def doctor(pack_dir, as_json):
    import app_gate as G, release as REL
    pack_dir = pathlib.Path(pack_dir).resolve(); items = []
    def item(name, ok, found, fix=None, required=True): items.append({"name": name, "ok": bool(ok), "found": found, "required": required, **({"fix": fix} if not ok and fix else {})})
    v = sys.version_info
    item("python >= 3.12", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro} ({sys.executable})", "use Python 3.12 or later (bash bootstrap.sh makes a .venv with it)")
    item("virtual environment", sys.prefix != getattr(sys, "base_prefix", sys.prefix), sys.prefix, "source .env (bootstrap.sh) so one interpreter and one architecture are used", required=False)
    try: P = PK.load(pack_dir); item("pack well-formed", True, f"{P['pack']['id']} {P['pack']['version']}")
    except Exception as e:
        item("pack well-formed", False, f"{type(e).__name__}: {e}", "the pack.yaml in this release is damaged; use a pristine release")
        return finish_doctor(items, as_json)
    rd = REL.release_digest(ROOT, pack_dir); seal = json.loads((pack_dir / W.SEAL).read_text()).get("release_digest") if (pack_dir / W.SEAL).exists() else None
    item("release matches its seal", rd == seal, f"{rd[:16]} (seal {str(seal)[:16]})", "the release on disk is not the sealed one: re-copy it from a trusted source")
    tools = G.tool_values(P)
    for n, t in (P.get("tools") or {}).items():
        val = tools[n]; path = shutil.which(val) or (val if os.path.exists(val) else None)
        item(f"tool {n} (${t['env']})", bool(path), val + ("" if path else " (not found)"), f"export {t['env']}=<path> (bash bootstrap.sh && source .env downloads it)")
    tc = G.toolchain(P, pack_dir, tools)
    for n, t in (P.get("toolchain") or {}).items():
        ok = str(tc.get(n, "")).strip() not in PT.UNAVAILABLE
        fix = t.get("install") or (f"pip install {t['python_package']} (inside the .venv)" if "python_package" in t else f"install {n} so that `{t['command'].split(';')[0]}` works")
        item(f"toolchain {n}", ok, str(tc.get(n))[:80], fix)
    for rt in (P.get("candidate") or {}).get("runtimes", []):
        if rt == "python": continue
        found = shutil.which(rt); item(f"candidate runtime {rt}", bool(found), found or "not on PATH", f"install {rt} (the judge runs candidates on it)")
    if "playwright" in (P.get("toolchain") or {}) and str(tc.get("playwright")) not in PT.UNAVAILABLE:
        item(*browser_check())
    return finish_doctor(items, as_json)


def browser_check():
    import browser as GB
    opts, sandboxed = GB.launch_options()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(**opts); ver = b.version; b.close()
        return ("browser launches", True, f"chromium {ver}, sandboxed={sandboxed}", None)
    except Exception as e:
        return ("browser launches", False, f"{type(e).__name__}: {str(e).splitlines()[0][:160]}",
                "python3 -m playwright install chromium, or export SEED_CHROMIUM=<chromium binary>; where Chromium's sandbox cannot run, "
                "SEED_ALLOW_UNSANDBOXED_BROWSER=1 for trusted candidates only (recorded; not release-ready)")


def finish_doctor(items, as_json):
    bad = [i for i in items if not i["ok"] and i["required"]]
    text = "\n".join(f"{'ok  ' if i['ok'] else ('MISSING' if i['required'] else 'note')} {i['name']}: {i['found']}" + (f"\n       fix: {i['fix']}" if i.get("fix") else "") for i in items)
    text += "\n" + ("ready: every tool this pack declares is available" if not bad else f"not ready: {len(bad)} required item(s) missing; a check that needs one is blocked (category toolchain_unavailable), never passed")
    emit(as_json, {"format": "pith.doctor/v1", "ready": not bad, "items": items}, text)
    return EXIT_OK if not bad else EXIT_NOT_OK


# ---------------------------------------------------------------- verify / packet
def verify(argv, as_json):
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    if not out: print("verify needs app_gate.py's --out EVIDENCE_DIR", file=sys.stderr); return EXIT_USAGE
    gate = HERE / "app_gate.py"
    if "--candidate" not in argv and "--policy-from" not in argv: cmd = [sys.executable, str(gate)] + argv
    else: cmd = [sys.executable, "-I", str(gate)] + argv
    r = subprocess.run(cmd, stdout=sys.stderr if as_json else None)
    f = pathlib.Path(out) / "task-packet.json"
    if not f.exists(): print(f"no task packet in {out} (the judge did not start: exit {r.returncode})", file=sys.stderr); return r.returncode or EXIT_NOT_OK
    pk = json.loads(f.read_text()); emit(as_json, pk, "\n" + PT.markdown(pk))
    return r.returncode


def packet(evidence, as_json):
    f = pathlib.Path(evidence) / "task-packet.json"
    if not f.exists(): print(f"{f}: no task packet (runs before v0.9.0 have none)", file=sys.stderr); return EXIT_USAGE
    pk = json.loads(f.read_text()); emit(as_json, pk, PT.markdown(pk)); return EXIT_OK if pk["state"] == "done" else EXIT_NOT_OK


# ---------------------------------------------------------------- pack new / pack check
def pack_new(name, out):
    tpl = ROOT / "templates" / "pack"
    if not tpl.exists(): print("pack new needs a Pith source checkout (templates/pack is not part of a release)", file=sys.stderr); return EXIT_USAGE
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", name): print("NAME: lower-case letters, digits and '-'", file=sys.stderr); return EXIT_USAGE
    out = pathlib.Path(out)
    if out.exists(): print(f"{out} exists; choose a new directory", file=sys.stderr); return EXIT_USAGE
    shutil.copytree(tpl, out, ignore=shutil.ignore_patterns(*W.CACHE_DIRS, *W.OS_METADATA))
    for p in out.rglob("*"):
        if p.is_file() and p.suffix in (".yaml", ".md", ".py", ".tla", ".cfg"):
            p.write_text(p.read_text().replace("__PACK__", name))
    print(f"draft pack {name} at {out}: start with INTENT.md, then the model, the harness and the wrong examples; "
          f"`python3 gate/cli.py pack check {out}` lists what is missing; docs/PACK-AUTHORING.md is the guide")
    return EXIT_OK


def pack_check(pack_dir, release_mode, reviews, keys, as_json, today=None):
    """Consistency and adequacy checks a pack's author runs before asking for review. Errors make a pack unfit to
    judge with; warnings are what a reviewer will ask about. Domain-free: everything comes from pack.yaml and the files it names."""
    pack_dir = pathlib.Path(pack_dir).resolve(); errors, warnings, info = [], [], {}
    try: P = PK.load(pack_dir)
    except Exception as e:
        errors.append(f"pack.yaml: {type(e).__name__}: {e}"); return finish_check(pack_dir, errors, warnings, info, as_json)
    info["pack"] = f"{P['pack']['id']} {P['pack']['version']}"
    checks = P.get("preflight", []) + P["checks"]; ids = {c["id"] for c in checks}; contracts = P.get("contracts", [])
    established = {e for c in checks for e in c.get("establishes", [])}
    if not contracts: errors.append("no contract records: a pack protects named requirements (docs/rfc/0001 § 5)")
    for c in contracts:
        where = f"contract {c['id']}"
        if not str(c.get("intent") or "").strip(): errors.append(f"{where}: no intent")
        if not c.get("semantics"): errors.append(f"{where}: no semantics (where the precise statement lives)")
        if c.get("change") not in ("presentation", "integration", "behavioral"): errors.append(f"{where}: change must be presentation, integration or behavioral")
        migs = {m.get("spec") for m in P.get("migrations", []) or []}
        if c.get("migration") and c["migration"] not in migs: errors.append(f"{where}: migration {c['migration']} is not one of the pack's migrations")
        if not c.get("verified_by") and c["id"] not in established and not c.get("migration"): errors.append(f"{where}: verified by no check and no migration")
        for s in (c.get("semantics") or {}).values():
            f = str(s).split()[0].split("#")[0]
            if "/" in f and f.split("/")[0] not in P["candidate"]["owned_dirs"] and not (pack_dir / f).exists() and not (ROOT / f).exists():
                errors.append(f"{where}: semantics names {f}, which does not exist")      # a candidate-generated file (gen/out/...) exists only in a build
        for w in c.get("wrong", []) or []:
            if not ((pack_dir / w).exists() or (ROOT / w).exists()): errors.append(f"{where}: wrong example {w} does not exist")
        if c.get("change") == "behavioral" and not c.get("wrong") and not any(c["id"] in x.get("establishes", []) and x.get("expect_exit") == "nonzero" for x in checks):
            warnings.append(f"{where}: behavioral, but no wrong candidate shows the pack rejects a violation of it")
    for m in P.get("migrations", []) or []:
        if not (pack_dir / str(m.get("spec"))).is_file(): errors.append(f"migration from {m.get('from')}: {m.get('spec')} does not exist")
        elif str(m.get("spec")).split("/")[0] not in P["policy_dirs"]: errors.append(f"migration from {m.get('from')}: {m.get('spec')} is outside the policy dirs, so it is not part of the release")
    for c in checks:
        if c.get("status") and not c.get("inputs") and c["kind"] not in ("manifest_choice", "attestation"): warnings.append(f"check {c['id']}: no inputs, so evidence invalidation cannot see what it read")
        if c.get("cacheable") and any(str(g).split("/")[0] in P["candidate"]["owned_dirs"] for g in c.get("inputs", [])) and c["kind"] == "command":
            warnings.append(f"check {c['id']}: cacheable but reads the candidate's files through a command; never cache a check that starts the candidate")
    params = P.get("parameters") or {}; choices = {c["key"] for c in P.get("preflight", []) if c["kind"] == "manifest_choice"}
    for k in P["candidate"]["manifest_allowlist"]:
        if k not in choices and not (isinstance(params.get(k), dict) and params[k].get("domain") and params[k].get("evidence")):
            errors.append(f"manifest key {k}: no defined domain and evidence (parameters.{k}: {{domain, evidence}}), so a value could silently inherit evidence it was never checked under")
    intent = (pack_dir / P["pack"]["intent"]) if P["pack"].get("intent") and (pack_dir / P["pack"]["intent"]).exists() else \
             (ROOT / P["pack"]["intent"]) if P["pack"].get("intent") else None
    if not intent or not intent.exists(): errors.append("pack.intent: the reviewed prose (INTENT.md) is missing")
    else:
        txt = intent.read_text(); unmentioned = [c["id"] for c in contracts if c.get("change") == "behavioral" and not re.search(rf"(?<![\w-]){re.escape(c['id'])}(?![\w-])", txt)]
        if unmentioned: warnings.append(f"INTENT.md does not mention behavioral records {unmentioned}: a reviewer cannot check them against plain words")
    wrong = pack_dir / "examples" / "wrong"
    if not (wrong / "expected.yaml").exists(): errors.append("examples/wrong/expected.yaml: no known-wrong applications with their expected refusals")
    else:
        exp = yaml.safe_load((wrong / "expected.yaml").read_text()) or {}
        for n, e in exp.items():
            if not (wrong / n).is_dir(): errors.append(f"examples/wrong/{n}: listed in expected.yaml but missing")
            if e.get("refused_at") and e["refused_at"] not in ids: errors.append(f"examples/wrong/{n}: refused_at {e['refused_at']} is not a check")
            if e.get("category") and e["category"] not in PT.CATEGORIES: errors.append(f"examples/wrong/{n}: category {e['category']} is not one of {PT.CATEGORIES}")
        info["wrong_applications"] = len(exp)
        if not exp: errors.append("examples/wrong/expected.yaml lists no wrong application")
    good = [d for d in (pack_dir / "examples").iterdir() if d.is_dir() and d.name != "wrong" and (d / W.MANIFEST).exists()] if (pack_dir / "examples").exists() else []
    info["conforming_examples"] = len(good)
    if len(good) < 2: warnings.append(f"{len(good)} conforming example(s): two different applications on one contract show presentation is free")
    if not P.get("domain_vocabulary"): warnings.append("no domain_vocabulary: CI cannot hold the evaluator to this pack's words (validation/domain_free.py)")
    if not P["pack"].get("maintainers"): errors.append("pack.maintainers: who answers for this pack")
    import release as REL
    rd = REL.release_digest(ROOT, pack_dir); info["release_digest"] = rd
    seal = json.loads((pack_dir / W.SEAL).read_text()).get("release_digest") if (pack_dir / W.SEAL).exists() else None
    if seal != rd: (errors if release_mode else warnings).append("not sealed at its current content (python3 gate/release.py seal --pack DIR)")
    # review: an independent, signed review of THIS release (gate/review.py sign-pack)
    import review as RV
    found = []
    rdir = pathlib.Path(reviews) if reviews else pack_dir / "reviews"
    for f in sorted(rdir.glob("*.json")) if rdir.exists() else []:
        for k in keys:
            ok, d = RV.verify_pack(f, k, release_digest=rd, pack_id=P["pack"]["id"], maintainers=P["pack"].get("maintainers", []), today=today)
            found.append({"review": str(f), "key": str(k), "ok": ok, "detail": d})
    info["reviews"] = found; info["independently_reviewed"] = any(r["ok"] for r in found)
    if release_mode and not info["independently_reviewed"]:
        errors.append("no valid independent review of this release: someone who is not a maintainer reviews intent, traces and wrong "
                      "candidates and signs it (gate/review.py sign-pack); a pack's author cannot certify their own acceptance checks")
    return finish_check(pack_dir, errors, warnings, info, as_json)


def finish_check(pack_dir, errors, warnings, info, as_json):
    stage = "unfit" if errors else ("released" if info.get("independently_reviewed") else "draft (fit to judge with; not independently reviewed)")
    text = "\n".join([f"pack {pack_dir}: {info.get('pack', '?')}"] + [f"ERROR   {e}" for e in errors] + [f"warning {w}" for w in warnings] +
                     [f"review  {'ok' if r['ok'] else 'invalid'}: {r['review']}: {r['detail']}" for r in info.get("reviews", [])] + [f"stage: {stage}"])
    emit(as_json, {"format": "pith.pack-check/v1", "pack_dir": str(pack_dir), "ok": not errors, "stage": stage, "errors": errors, "warnings": warnings, **info}, text)
    return EXIT_OK if not errors else EXIT_NOT_OK


# ---------------------------------------------------------------- adopt
def adopt(release, project, subsystem, include, name, as_json):
    """Prepare an existing project to have ONE workflow judged against a pack. Writes app.manifest.yaml and PITH.md (the
    adoption record) into the project; never copies the release into it (the operator keeps the release pristine) and
    never overwrites. Reports collisions: a project directory named like a pack policy dir would be replaced by the
    pack's in the judged workspace, so the project's code cannot live there."""
    import release as REL
    release, project = pathlib.Path(release).resolve(), pathlib.Path(project).resolve()
    P = PK.load(release); rd = REL.release_digest(release, release)
    seal = json.loads((release / W.SEAL).read_text()).get("release_digest") if (release / W.SEAL).exists() else None
    problems, notes, written = [], [], []
    if rd != seal: problems.append(f"the release at {release} does not match its seal; build one with gate/release.py build")
    if "include" not in P["candidate"]["manifest_allowlist"]: problems.append(f"{P['pack']['id']} does not allow existing-project adoption (no `include` manifest key)")
    policy = [d for d in P["policy_dirs"]] + ["gate"]
    clash = [d for d in policy if (project / d).exists()]
    if clash: problems.append(f"the project has {clash}, which are this pack's policy dirs: in the judged workspace they are the pack's, so code there would be replaced; move it")
    problems += W.include_problems(list(include), policy, project)
    owned = P["candidate"]["owned_dirs"]
    present = [d for d in owned if (project / d).exists()]
    if present: notes.append(f"the project already has {present}: everything under them becomes part of the judged artifact (keep them to the pack's entrypoints)")
    needed = sorted({f for c in P.get("checks", []) if c["kind"] == "files_present" and _applies(c, P) for f in c["files"]})
    if not problems:
        m = project / W.MANIFEST
        if m.exists(): notes.append(f"{W.MANIFEST} exists; left as is (it must name include: {list(include)} and subsystem)")
        else:
            defaults = {c["key"]: c.get("default") for c in P.get("preflight", []) if c["kind"] == "manifest_choice"}
            body = {"name": name or project.name, **{k: v for k, v in defaults.items() if v is not None}, "include": list(include), "subsystem": subsystem}
            m.write_text(f"# app.manifest.yaml — this project's adoption of {P['pack']['id']} (written by gate/cli.py adopt). Only the keys in the\n"
                         f"# pack's manifest_allowlist; include lists the project code the entrypoints use; nothing else of the project is judged.\n"
                         + yaml.safe_dump(body, sort_keys=False, width=1000)); written.append(str(m))
        rec = project / "PITH.md"
        if rec.exists(): notes.append("PITH.md exists; left as is")
        else:
            rec.write_text(ADOPTION_RECORD.format(pack=P["pack"]["id"], version=P["pack"]["version"], release=rd, subsystem=subsystem,
                                                  include=", ".join(include) or "(none)", owned=", ".join(d + "/" for d in owned),
                                                  needed="\n".join(f"- `{f}`" + (" (present)" if (project / f).exists() else "") for f in needed) or "- (see the pack's harness contract)",
                                                  date=time.strftime("%Y-%m-%d"), records="\n".join(f"- {c['id']}: {c.get('intent')}" for c in P.get("contracts", []) if c.get("change") == "behavioral"),
                                                  judge=f"python3 -I {release}/gate/app_gate.py --candidate {project} --out <fresh dir outside the project> --expected-release {rd}"))
            written.append(str(rec))
    out = {"format": "pith.adopt/v1", "ok": not problems, "pack": P["pack"]["id"], "release_digest": rd, "project": str(project), "subsystem": subsystem,
           "include": list(include), "entrypoints_to_write": [f for f in needed if not (project / f).exists()], "written": written, "problems": problems, "notes": notes,
           "judge": f"python3 -I {release}/gate/app_gate.py --candidate {project} --out <fresh dir> --expected-release {rd}"}
    text = "\n".join([f"adopting {P['pack']['id']} into {project} for: {subsystem}"] + [f"PROBLEM {p}" for p in problems] + [f"note    {n}" for n in notes] +
                     [f"wrote   {w}" for w in written] + ([f"next    write {out['entrypoints_to_write']} to the pack's contract, then judge:\n        {out['judge']}"] if not problems else []))
    emit(as_json, out, text)
    return EXIT_OK if not problems else EXIT_NOT_OK


def _applies(c, P):
    """A `when` condition on a check holds under the pack's manifest defaults (a project adopting starts from them)."""
    d = {x["key"]: x.get("default") for x in P.get("preflight", []) if x["kind"] == "manifest_choice"}
    return all(d.get(k) == v for k, v in ((c.get("when") or {}).get("manifest") or {}).items())


ADOPTION_RECORD = """# Pith adoption record

This project protects **one workflow** with the contract pack `{pack}` {version} (release `{release}`).
Written by `gate/cli.py adopt` on {date}; keep it up to date as the adoption proceeds (docs/ADOPTING.md).

## 1. The operation
Subsystem covered: {subsystem}

Project code the pack's entrypoints use (`include`): {include}. The judge copies only these paths and the pack's
agent-owned directories ({owned}) into the judged artifact. **Nothing else in this repository is covered**, and
"Pith is installed" does not mean the rest of the application is checked.

## 2. The protected behaviour
The pack's behavioral contract records (its INTENT.md explains them):

{records}

Where this project's current behaviour differs from them, decide here whether to change the code or not to adopt.

## 3. The independent checks
Entrypoints the pack's harness starts (its service contract says what each must do):

{needed}

Judge with the operator's pristine release, pinned (keep the release outside this repository):

    {judge}

## 4. Replace or strengthen
Record each refusal the judge reported, its category and what was changed (code, not checks), until it passes.

| Date | First failure | Category | Change made |
|---|---|---|---|
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] and argv[0] in DELEGATED:                     # v0.10.0: the evolution tools, each with its own arguments
        return subprocess.run([sys.executable, str(HERE / DELEGATED[argv[0]])] + argv[1:]).returncode
    if argv[:1] == ["verify"]:
        rest = argv[1:]; as_json = "--json" in rest; rest = [x for x in rest if x != "--json"]
        if rest[:1] == ["--"]: rest = rest[1:]
        return verify(rest, as_json)
    ap = argparse.ArgumentParser(prog="pith", description=__doc__.split("\n\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor"); d.add_argument("--pack", default=str(ROOT)); d.add_argument("--json", action="store_true")
    sub.add_parser("verify", help="-- <app_gate.py arguments>")
    for name, mod in DELEGATED.items(): sub.add_parser(name, help=f"gate/{mod} (its own arguments)")
    k = sub.add_parser("packet"); k.add_argument("evidence"); k.add_argument("--json", action="store_true")
    pk = sub.add_parser("pack"); ps = pk.add_subparsers(dest="pcmd", required=True)
    n = ps.add_parser("new"); n.add_argument("name"); n.add_argument("--out", required=True)
    c = ps.add_parser("check"); c.add_argument("dir"); c.add_argument("--release", action="store_true"); c.add_argument("--reviews", default=None)
    c.add_argument("--reviewer-key", action="append", default=[]); c.add_argument("--today", default=None); c.add_argument("--json", action="store_true")
    a = sub.add_parser("adopt"); a.add_argument("--release", required=True); a.add_argument("--project", required=True); a.add_argument("--subsystem", required=True)
    a.add_argument("--include", action="append", default=[]); a.add_argument("--name", default=None); a.add_argument("--json", action="store_true")
    try: x = ap.parse_args(argv)
    except SystemExit as e: return EXIT_USAGE if e.code else EXIT_OK
    if x.cmd == "doctor": return doctor(x.pack, x.json)
    if x.cmd == "packet": return packet(x.evidence, x.json)
    if x.cmd == "pack" and x.pcmd == "new": return pack_new(x.name, x.out)
    if x.cmd == "pack" and x.pcmd == "check": return pack_check(x.dir, x.release, x.reviews, x.reviewer_key, x.json, x.today)
    if x.cmd == "adopt": return adopt(x.release, x.project, x.subsystem, x.include, x.name, x.json)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
