#!/usr/bin/env python3
"""
gate/redteam.py — adversarial adequacy: mutants a pack's gate accepts although they violate its intent, and the ratchet
that turns each one into a permanent known-wrong fixture. FROZEN. Domain-free. A maintainers' tool, not a judge.

    python3 gate/redteam.py run     DIR [--packet FILE ...] [--generate] [--max N] [--out OUT] [--json]
    python3 gate/redteam.py promote DIR [--out OUT] [--json]
    (python3 gate/cli.py pack redteam DIR ... runs `run`; with --promote, `promote`)

An ADEQUACY GAP is a mutant that the pack's gate accepts although a WITNESS shows it violates the pack's intent: an
executable check that fails on the mutant and passes on the pack's reference. Both halves are mechanical. Targets, as
the pack declares them (pack.yaml `redteam`, docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 4):

  examples   a candidate mutant (files overlaid on a reference example), judged by the pack's own release exactly as a
             candidate is (gate/app_gate.py); its witness is a test run in the mutant's judged workspace
  spec       a design the release's own checked properties should reject; `accepts` and `violates` are the pack's
             commands ({design}, {property}, {work}); its witness is a property the reference satisfies

Verdicts: killed (the gate refuses the mutant; which check refused it is recorded), invalid-witness (the witness fails
on the reference), equivalent (the witness passes on the mutant), survivor (accepted, witness fails on the mutant and
passes on the reference: a gap), unkilled (a generated mutant the gate accepts, with no witness yet: a candidate for a
gap, not a gap). Saboteur packets (gate/schemas/saboteur-packet.schema.json) bring mutants and witnesses from outside;
--generate applies a small deterministic operator set to the files `examples.mutate` names.

The ratchet (the pack's `redteam.gaps`, format pith.redteam-gaps/v1): every survivor is recorded `open`, and
`gate/cli.py pack check` reports open gaps (an error with --release). A recorded gap that a later run finds killed
becomes `killed`; `promote` writes it into the pack's known-wrong suite (examples: a complete candidate under
examples/wrong/ with an expected.yaml entry taken from the refusal it actually got; spec: the design into
`spec.wrong_dir`) and marks it `promoted`. A gap cannot close silently.

Packets run with the maintainer's privileges (a witness is code that starts the candidate's service through the pack's
harness): run packets from outside the project in the isolation profile or a throwaway environment.
"""
import argparse, fnmatch, io, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, tokenize
import yaml

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import workspace as W, release as REL, pack as PK

PACKET = "pith.saboteur-packet/v1"; REPORT = "pith.redteam-report/v1"; GAPS = "pith.redteam-gaps/v1"
FLIP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "=="}


# ---------------------------------------------------------------- the pack's own judge, on a mutant
class Release:
    """The pack's release built once (gate/release.py build) and its digest; mutants are judged against it."""
    def __init__(self, pack_dir, tmp):
        self.pack = pathlib.Path(pack_dir).resolve(); self.P = PK.load(self.pack)
        self.dir = REL.build(self.pack, tmp / "release"); self.digest = REL.release_digest(self.dir, self.dir)

    def candidate(self, base, files, tmp, name):
        """A candidate directory as a judge receives it: the release's files, the reference example, the mutant's files."""
        c = tmp / name
        if c.exists(): shutil.rmtree(c)
        c.mkdir(parents=True)
        for d in W.load_pack_policy(self.dir)[0]:
            if (self.dir / d).exists(): shutil.copytree(self.dir / d, c / d)
        for f in (W.PACK_FILE, W.SEAL): shutil.copy(self.dir / f, c / f)
        shutil.copytree(self.pack / base, c, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*W.CACHE_DIRS, *W.OS_METADATA))
        for rel, text in (files or {}).items():
            (c / rel).parent.mkdir(parents=True, exist_ok=True); (c / rel).write_text(text)
        for f in [c / "claims-from-release.json", *c.glob("*.example")]: f.unlink(missing_ok=True)
        return c

    def judge(self, cand, out, reuse=None):
        """(accepted, first refusal {check, failing_tests}, statuses). Accepted: every status at its ready value, except
        the ones a person's review decides (no run can have them)."""
        cmd = [sys.executable, "-I", str(self.dir / "gate/app_gate.py"), "--candidate", str(cand), "--expected-release", self.digest, "--out", str(out)]
        if reuse and (pathlib.Path(reuse) / "evidence.json").exists(): cmd += ["--reuse", str(reuse)]
        subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if not (out / "app-claims.json").exists(): return False, {"check": None, "why": "the judge produced no claims"}, {}
        c = json.loads((out / "app-claims.json").read_text())
        review = {x.get("status") for x in self.P.get("checks", []) if x.get("method") == "review"}
        statuses = {s: c.get(s) for s in self.P.get("statuses", {})}
        unready = [s for s, v in statuses.items() if s not in review and not ready(self.P, s, v)]
        fails = [x for x in c.get("checks", []) if x.get("result") == "fail"]; first = fails[0] if fails else {}
        return not unready, {"check": first.get("id"), "failing_tests": sorted(set(re.findall(r"FAILED \S+::(\w+)", first.get("why") or ""))),
                             "category": first.get("category"), "unready": unready}, statuses

    def witness(self, cand, test_source, out):
        """Run a witness test in the candidate's judged workspace; True when it passes."""
        ws = W.assemble(cand, self.dir, out / "witness-artifact")
        try:
            (ws / "redteam_witness.py").write_text(test_source)
            pytest = (self.P.get("pytest") or "{python} -m pytest -q").replace("{python}", sys.executable).replace("{root}", str(ws))
            cmd = (self.P.get("redteam", {}).get("witness") or "{pytest} {witness}").replace("{pytest}", pytest).replace("{python}", sys.executable).replace("{witness}", "redteam_witness.py")
            r = subprocess.run(cmd, shell=True, cwd=ws, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
            (out / "witness.log").write_text(r.stdout + r.stderr)
            return r.returncode == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True); shutil.rmtree(out / "witness-artifact", ignore_errors=True)

    def spec_cmd(self, key, design, prop, work):
        S = self.P["redteam"]["spec"]
        cmd = S[key].replace("{python}", sys.executable).replace("{design}", str(design)).replace("{property}", prop or "").replace("{work}", str(work))
        for n, t in (self.P.get("tools") or {}).items(): cmd = cmd.replace("{" + n + "}", os.environ.get(t["env"], t.get("default", "")))
        r = subprocess.run(cmd, shell=True, cwd=self.dir, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr)[-1500:]


def ready(P, name, value):
    cond = P["statuses"][name]["ready"]
    return isinstance(value, str) and (value.startswith(cond["startswith"]) if "startswith" in cond else value == cond["equals"])


# ---------------------------------------------------------------- generated mutants (deterministic operators)
def mutants_of(path, text):
    """[(id, description, mutated text)] for one Python file: comparison flips, integer constants off by one, booleans
    negated, a `with ...lock...:` block run without its lock. Deterministic order."""
    out = []; lines = text.splitlines(keepends=True)
    def at(row, col, old, new, what):
        L = list(lines); s = L[row - 1]; assert s[col:col + len(old)] == old
        L[row - 1] = s[:col] + new + s[col + len(old):]
        out.append((f"{path}:{row}:{col}:{what}", f"{path} line {row}: {old!r} -> {new!r} ({what})", "".join(L)))
    try: toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError): return out
    for t in toks:
        (row, col) = t.start
        if t.type == tokenize.OP and t.string in FLIP: at(row, col, t.string, FLIP[t.string], "flip-comparison")
        elif t.type == tokenize.NUMBER and re.fullmatch(r"\d+", t.string) and int(t.string) < 10 ** 6:
            at(row, col, t.string, str(int(t.string) + 1), "constant+1")
            if int(t.string) > 0: at(row, col, t.string, str(int(t.string) - 1), "constant-1")
        elif t.type == tokenize.NAME and t.string in ("True", "False"): at(row, col, t.string, "False" if t.string == "True" else "True", "negate-boolean")
    for i, s in enumerate(lines, 1):
        m = re.match(r"^(\s*)with\s+([^:]*lock[^:]*):\s*(#.*)?$", s.rstrip("\n"), re.I)
        if m:
            L = list(lines); L[i - 1] = f"{m.group(1)}if True:  # (redteam: {m.group(2).strip()} removed)\n"
            out.append((f"{path}:{i}:0:drop-lock", f"{path} line {i}: run the block without {m.group(2).strip()} (drop-lock)", "".join(L)))
    return out


def generated(pack, R):
    E = R.get("examples") or {}; base = pack / E["base"]; out = []
    for p in sorted(base.rglob("*.py")):
        rel = str(p.relative_to(base))
        if any(fnmatch.fnmatch(rel, g) or (g.endswith("/**") and rel.startswith(g[:-2])) for g in E.get("mutate", [])):
            out += [{"id": i, "source": "generated", "target": "examples", "description": d, "base": E["base"], "files": {rel: t}} for i, d, t in mutants_of(rel, p.read_text())]
    return out


# ---------------------------------------------------------------- the run
def load_packet(f, pack):
    K = yaml.safe_load(pathlib.Path(f).read_text())
    errs = []
    try:
        import jsonschema
        S = json.loads((HERE / "schemas/saboteur-packet.schema.json").read_text())
        errs = [e.message for e in jsonschema.Draft202012Validator(S).iter_errors(K)]
    except ImportError: pass
    if K.get("format") != PACKET: errs.append(f"format is not {PACKET}")
    if K.get("pack") != pack.P["pack"]["id"]: errs.append(f"packet is for {K.get('pack')}, not {pack.P['pack']['id']}")
    return K, errs


def run(pack_dir, packets=(), generate=False, out=None, max_mutants=60):
    pack_dir = pathlib.Path(pack_dir).resolve(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="redteam-"))
    out = pathlib.Path(out).resolve() if out else tmp / "out"; out.mkdir(parents=True, exist_ok=True)
    rel = Release(pack_dir, tmp); R = rel.P.get("redteam")
    rep = {"format": REPORT, "pack": rel.P["pack"]["id"], "version": rel.P["pack"].get("version"), "release_digest": rel.digest,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mutants": [], "problems": []}
    if not R: rep["problems"].append("pack.yaml declares no redteam section"); return finish(rep, pack_dir, None)
    ref = None; E = R.get("examples")
    if E:   # the reference example must itself be accepted, or nothing can be said about mutants of it
        ref = out / "reference"; shutil.rmtree(ref, ignore_errors=True)
        ok, first, _ = rel.judge(rel.candidate(E["base"], {}, tmp, "ref-cand"), ref)
        if not ok: rep["problems"].append(f"the reference example {E['base']} is not accepted ({first}): fix it before red-teaming"); return finish(rep, pack_dir, R)
    items = []
    for f in packets:
        K, errs = load_packet(f, rel)
        if errs: rep["problems"].append(f"{f}: {'; '.join(errs)}"); continue
        items.append({"id": K["id"], "source": f"packet {pathlib.Path(f).name}", "target": K["target"], "packet": K})
    gens = generated(pack_dir, R)[:max_mutants] if (generate and E) else []
    byid = {g["id"]: g for g in gens}
    for it in items:   # a packet may confirm a generated mutant by its id instead of carrying files
        g = (it["packet"].get("mutant") or {}).get("generated")
        if g: byid.pop(g, None)
    items += list(byid.values())
    for n, it in enumerate(items):
        d = out / f"m{n:03d}"; shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        it.update(spec_one(rel, it, d, tmp) if it["target"] == "spec" else example_one(rel, it, d, tmp, ref, pack_dir))
        it.pop("packet", None)
        if it["verdict"] != "survivor": it.pop("files", None)            # a survivor's files are its gap's evidence and what promote writes
        rep["mutants"].append(it)
        print(f"[{it['verdict']:>15}] {it['id']}" + (f" — refused at {it.get('refused_at')}" if it.get("refused_at") else ""), file=sys.stderr)
    return finish(rep, pack_dir, R)


def example_one(rel, it, d, tmp, ref, pack_dir):
    K = it.get("packet") or {}; M = K.get("mutant") or {}; E = rel.P["redteam"]["examples"]
    files = it.get("files") or M.get("files")
    if not files and M.get("generated"):
        g = next((x for x in generated(pack_dir, rel.P["redteam"]) if x["id"] == M["generated"]), None)
        if g is None: return {"verdict": "invalid", "detail": f"no generated mutant {M['generated']}"}
        files = g["files"]; it["description"] = g["description"]
    cand = rel.candidate(M.get("base") or E["base"], files, tmp, "cand")
    ok, first, _ = rel.judge(cand, d / "evidence", reuse=ref)
    res = {"records": (K.get("claims") or {}).get("records", []), "mutant_files": sorted(files or {})}
    if not ok: return {**res, "verdict": "killed", "refused_at": first.get("check"), "failing_tests": first.get("failing_tests", []), "category": first.get("category")}
    W_ = (K.get("witness") or {}).get("test")
    if not W_: return {**res, "verdict": "unkilled", "detail": "accepted by the gate; no witness yet (a candidate for a gap, or an equivalent mutant)"}
    if not rel.witness(rel.candidate(E["base"], {}, tmp, "ref-w"), W_, d / "w-ref"): return {**res, "verdict": "invalid-witness", "detail": "the witness fails on the reference"}
    if rel.witness(cand, W_, d / "w-mut"): return {**res, "verdict": "equivalent", "detail": "the witness passes on the mutant"}
    shutil.copytree(cand, d / "candidate", ignore=shutil.ignore_patterns(*W.load_pack_policy(rel.dir)[0], W.PACK_FILE, W.SEAL))
    return {**res, "verdict": "survivor", "detail": "accepted by the gate; the witness fails on it and passes on the reference",
            "witness": W_, "files": files}


def spec_one(rel, it, d, tmp):
    K = it["packet"]; M = K.get("mutant") or {}; prop = (K.get("witness") or {}).get("property"); S = rel.P["redteam"].get("spec")
    if not S: return {"verdict": "invalid", "detail": "the pack declares no spec target"}
    design = d / M["design"]["name"]; design.write_text(M["design"]["content"])
    res = {"records": (K.get("claims") or {}).get("records", []), "design": M["design"]["name"], "property": prop}
    # the pack's commands exit 0 (accepted / holds), 1 (rejected / violated) or anything else (the tool did not run):
    # the last is never read as a verdict
    code, o = rel.spec_cmd("accepts", design, None, d)
    if code not in (0, 1): return {**res, "verdict": "invalid", "detail": f"the accepts command did not run (exit {code}): " + o[-300:]}
    if code == 1: return {**res, "verdict": "killed", "refused_at": "spec.accepts", "detail": o[-400:]}
    if not prop: return {**res, "verdict": "unkilled", "detail": "accepted by the release's checked properties; no witness property"}
    code, o = rel.spec_cmd("violates", rel.dir / S["reference"], prop, d)
    if code != 0: return {**res, "verdict": "invalid-witness" if code == 1 else "invalid", "detail": f"the reference check exited {code}: " + o[-300:]}
    code, o = rel.spec_cmd("violates", design, prop, d)
    if code not in (0, 1): return {**res, "verdict": "invalid", "detail": f"the violates command did not run (exit {code}): " + o[-300:]}
    if code == 0: return {**res, "verdict": "equivalent", "detail": f"the design satisfies {prop}"}
    return {**res, "verdict": "survivor", "detail": f"the release's checked properties accept the design; it violates {prop}, which the reference satisfies",
            "content": M["design"]["content"]}


# ---------------------------------------------------------------- the gap record
def gaps_path(pack_dir, R): return pathlib.Path(pack_dir) / (R or {}).get("gaps", "redteam/gaps.yaml")


def load_gaps(pack_dir, R):
    p = gaps_path(pack_dir, R)
    L = yaml.safe_load(p.read_text()) if p.exists() else None
    return L or {"format": GAPS, "gaps": []}


def finish(rep, pack_dir, R):
    rep["survivors"] = [m["id"] for m in rep["mutants"] if m["verdict"] == "survivor"]
    rep["unkilled"] = [m["id"] for m in rep["mutants"] if m["verdict"] == "unkilled"]
    rep["killed"] = [m["id"] for m in rep["mutants"] if m["verdict"] == "killed"]
    if R is not None and not rep["problems"]:
        L = load_gaps(pack_dir, R); gaps = {g["id"]: g for g in L["gaps"]}; today = time.strftime("%Y-%m-%d")
        for m in rep["mutants"]:
            g = gaps.get(m["id"])
            if m["verdict"] == "survivor" and (g is None or g["status"] in ("open", "killed")):
                gaps[m["id"]] = {**(g or {"found": today}), "id": m["id"], "status": "open", "target": m["target"], "source": m["source"],
                                 "records": m.get("records", []), "detail": m["detail"], "release_digest": rep["release_digest"],
                                 "mutant": {k: m[k] for k in ("files", "witness", "design", "property", "content") if k in m}}
            elif m["verdict"] == "killed" and g is not None and g["status"] == "open":
                g.update(status="killed", killed={"date": today, "release_digest": rep["release_digest"], "refused_at": m.get("refused_at"),
                                                  "failing_tests": m.get("failing_tests", []), "category": m.get("category")})
        L["gaps"] = sorted(gaps.values(), key=lambda g: g["id"])
        p = gaps_path(pack_dir, R); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# The adequacy ratchet (gate/redteam.py; docs/rfc/0007 § 4): every gap a red-team run confirmed, and what became of it.\n"
                     "# open: accepted by the gate, shown wrong by its witness (gate/cli.py pack check reports it); killed: refused now,\n"
                     "# waiting to be promoted; promoted: a permanent known-wrong fixture. Entries are never deleted.\n" + yaml.safe_dump(L, sort_keys=False, width=1000))
        rep["gaps"] = {"path": str(p), "open": sorted(g["id"] for g in L["gaps"] if g["status"] == "open"),
                         "killed": sorted(g["id"] for g in L["gaps"] if g["status"] == "killed")}
    rep["ok"] = not rep["problems"] and not rep["survivors"]
    return rep


def promote(pack_dir, out=None):
    """Every `killed` gap into the pack's known-wrong suite, with the refusal it actually got; marked `promoted`."""
    pack_dir = pathlib.Path(pack_dir).resolve(); P = PK.load(pack_dir); R = P.get("redteam") or {}
    L = load_gaps(pack_dir, R); done = []; problems = []
    for g in L["gaps"]:
        if g["status"] != "killed": continue
        name = re.sub(r"[^a-z0-9-]+", "-", g["id"].lower()).strip("-")[:48]
        if g["target"] == "examples":
            E = R["examples"]; wrong = pack_dir / "examples/wrong"; dst = wrong / name
            if dst.exists(): problems.append(f"{dst} exists"); continue
            shutil.copytree(pack_dir / E["base"], dst, ignore=shutil.ignore_patterns(*W.CACHE_DIRS, *W.OS_METADATA))
            for rel_, text in (g["mutant"].get("files") or {}).items(): (dst / rel_).write_text(text)
            ef = wrong / "expected.yaml"; exp = (yaml.safe_load(ef.read_text()) or {}) if ef.exists() else {}
            k = g["killed"]
            exp[name] = {"source": f"promoted by gate/redteam.py from gap {g['id']} ({g['source']}): {g['detail']}", "refused_at": k["refused_at"],
                         "failing_tests": k["failing_tests"], **({"category": k["category"]} if k.get("category") else {}),
                         **({"contracts": g["records"]} if g.get("records") else {}), "promoted_from": g["id"]}
            ef.write_text((ef.read_text().rstrip("\n") + "\n" if ef.exists() else "") + yaml.safe_dump({name: exp[name]}, sort_keys=False, width=1000))
            g.update(status="promoted", promoted={"date": time.strftime("%Y-%m-%d"), "to": str(dst.relative_to(pack_dir))})
        else:
            S = R["spec"]; dst = pack_dir / S["wrong_dir"] / g["mutant"]["design"]
            if dst.exists(): problems.append(f"{dst} exists"); continue
            dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(g["mutant"]["content"])
            g.update(status="promoted", promoted={"date": time.strftime("%Y-%m-%d"), "to": str(dst.relative_to(pack_dir))})
        done.append({"id": g["id"], "to": g["promoted"]["to"]})
    p = gaps_path(pack_dir, R)
    if p.exists(): p.write_text(p.read_text().split("format:")[0] + yaml.safe_dump(L, sort_keys=False, width=1000))
    return {"format": REPORT, "pack": P["pack"]["id"], "promoted": done, "problems": problems, "ok": not problems,
            "note": "promoted fixtures change the pack's adequacy material; a spec fixture needs the pack's adequacy check to cover its directory, and the pack is resealed by its maintainers"}


def open_gaps(pack_dir, P):
    """Ids of open gaps in the pack's gap record (gate/cli.py pack check)."""
    R = P.get("redteam")
    if not R: return []
    return sorted(g["id"] for g in load_gaps(pack_dir, R)["gaps"] if g["status"] == "open")


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("dir"); r.add_argument("--packet", action="append", default=[]); r.add_argument("--generate", action="store_true")
    r.add_argument("--max", type=int, default=60); r.add_argument("--out"); r.add_argument("--json", action="store_true")
    p = sub.add_parser("promote"); p.add_argument("dir"); p.add_argument("--out"); p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = run(a.dir, a.packet, a.generate, a.out, a.max) if a.cmd == "run" else promote(a.dir, a.out)
    if a.out: pathlib.Path(a.out).mkdir(parents=True, exist_ok=True); (pathlib.Path(a.out) / "redteam-report.json").write_text(json.dumps(rep, indent=1))
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for x in rep.get("problems", []): print(f"PROBLEM {x}")
        if a.cmd == "run":
            print(f"{len(rep['mutants'])} mutants: {len(rep['killed'])} killed, {len(rep['survivors'])} survivors (gaps), {len(rep['unkilled'])} unkilled (no witness yet)")
            for s in rep["survivors"]: print(f"  GAP {s}")
            if rep.get("gaps"): print(f"gap record {rep['gaps']['path']}: open {rep['gaps']['open']}; killed, ready to promote {rep['gaps']['killed']}")
        else:
            for x in rep["promoted"]: print(f"promoted {x['id']} -> {x['to']}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
