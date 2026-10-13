"""
gate/kinds.py — the kinds of check a pack can declare. FROZEN. Domain-free.

Each kind knows how to run one sort of tool and interpret its outcome; the pack supplies every path, pattern,
command, expectation and sentence. A kind returns a Result; the judge turns it into a report line and an evidence
record. Kinds never import candidate code. The only pack code a kind executes in the judge's process is an
`adapter`, which must live in the pack's frozen policy dirs (checked by gate/pack.py).

  command            run a command in the judged workspace; pass on exit 0 (or, with expect_exit: nonzero, on a refusal:
                     a known-wrong case the tool must reject); optional `count` regex, `export` of JSON; {item} from `each`
  files_present      every listed file exists
  source_rules       regex obligations on one source file: `require`, `forbid_lines`, `forbid_definitions`
  tlc                TLC model check of a module + cfg copied into a scratch dir; expect `no_error` or {violated: X} (an invariant or an action property)
  regenerated        listed generated files equal what the pack's generator produces now (restored afterwards)
  manifest_choice    a manifest key takes one of the pack's allowed values (or its default)
  manifest_commands  commands the manifest lists (supplementary, reported only)
  adapter            pack-supplied module with run(ctx) -> dict (a delivery adapter: browser, CLI, library, ...); it may report a
                     failure_category and the contract ids it found failing (v0.9.0, gate/packet.py)
  attestation        signed human-review attestation (gate/review.py) covering the pack's required evaluations
"""
import importlib.util, json, pathlib, re, shutil, tempfile
from dataclasses import dataclass, field
import yaml


@dataclass
class Result:
    ok: bool
    claim: str
    why: str = None
    outcome: str = None                 # a status value this check reports (adapter, attestation)
    outputs: dict = field(default_factory=dict)          # exported values (also stored in the evidence record)
    detail: dict = None                 # written to claims[check.claims_key]
    release_conditions: list = field(default_factory=list)   # [(name, ok, requirement)] the adapter adds to release_ready
    category: str = None                # on failure: what the kind or adapter knows about it (gate/packet.py CATEGORIES); v0.9.0
    failing_contracts: list = field(default_factory=list)    # contract record ids an adapter reports as failing; v0.9.0


class Fmt(dict):
    def __missing__(self, k): return "{" + k + "}"


def fmt(s, **kw): return (s or "").format_map(Fmt(kw))


def k_command(c, ctx):
    code, o = ctx.sh(fmt(ctx.subst(c["command"]), item=c.get("item", "")))
    ok = (code != 0) if c.get("expect_exit") == "nonzero" else (code == 0)
    n = re.search(c["count"], o) if c.get("count") else None
    out = {}
    for name, e in (c.get("export") or {}).items():
        try: out[name] = json.loads((ctx.root / e["json"]).read_text()).get(e["key"])
        except Exception: pass
    why = fmt(c["why"], item=c.get("item", "")) if (c.get("why") and c.get("expect_exit") == "nonzero") else o[-int(c.get("why_tail", 3000)):]
    return Result(ok, fmt(c["claim"], count=n.group(1) if n else "?", item=c.get("item", "")), why, outputs=out,
                  category="toolchain_unavailable" if code in (126, 127) else None,
                  failing_contracts=[] if ok else _named_in_failures(o, [x["id"] for x in (getattr(ctx, "pack", None) or {}).get("contracts", [])]))


def _named_in_failures(o, ids):
    """Contract record ids named in the head of each failing pytest test (its source up to the failing line, docstring
    included), over the whole output: the tail kept as `why` can lose the first failure when several fail."""
    found = []
    for sec in re.split(r"(?m)^_{3,} \S[^\n]* _{3,}$", o)[1:]:
        head = sec.split("\nE ", 1)[0][:4000]
        found += [i for i in ids if i not in found and re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", head)]
    return found


def k_files_present(c, ctx):
    missing = [f for f in c["files"] if not (ctx.root / f).exists()]
    return Result(not missing, c["claim"], fmt(c.get("why"), missing=missing))


def k_source_rules(c, ctx):
    src = (ctx.root / c["file"]).read_text()
    required = all(re.search(p, src) for p in c.get("require", []))
    lines = [l.strip() for l in src.splitlines() for p in c.get("forbid_lines", []) if re.search(p, l)]
    defined = [n for n in c.get("forbid_definitions", []) if re.search(rf"^\s*{re.escape(n)}\s*==", src, re.M)]
    return Result(required and not lines and not defined, c["claim"], fmt(c.get("why"), required=required, lines=lines, defined=defined))


def _tlc_why(o):
    m = re.search(r"Error: (Invariant \w+ is violated|Action property \w+ is violated|Temporal properties were violated)", o)
    i = o.find("The behavior up to this point is:")
    return (m.group(1) if m else "TLC did not report success") + ("\n" + o[i:i + 1800] if i >= 0 else "\n" + o[-800:])


def k_tlc(c, ctx):
    item = c.get("item", "")
    work = pathlib.Path(tempfile.mkdtemp(dir=ctx.root / c.get("workdir", ".")))
    try:
        src = ctx.root / c["copy"]["from"]
        for f in src.iterdir():
            if f.suffix in c["copy"]["suffixes"]: shutil.copy(f, work)
        for frm, to in (c.get("module_file") or {}).items(): shutil.copy(ctx.root / frm, work / to)
        cfg = c.get("cfg")
        if c.get("cfg_from"):
            cf = c["cfg_from"]; cfg = f"cov_{item}.cfg"
            (work / cfg).write_text((work / cf["base"]).read_text().split(cf["cut_at"])[0] + fmt(cf["append"], item=item))
        jar = ctx.subst(c["jar"])
        code, o = ctx.sh(f"java -XX:+UseParallelGC -cp {jar} tlc2.TLC -nowarning -workers 2 -deadlock -config {cfg} {c['module']}", cwd=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    exp = c["expect"]
    if exp == "no_error": ok = "No error has been found" in o; why = _tlc_why(o)
    else:       # an invariant, or an action property ([][A]_v), named X: TLC reports either as "<kind> X is violated"
        x = fmt(exp["violated"], item=item); ok = f"Invariant {x} is violated" in o or f"Action property {x} is violated" in o
        why = fmt(c.get("why"), item=item) if c.get("why") and ok else o[-800:]   # on failure, what TLC actually said
    ran = re.search(r"TLC2 Version|Starting\.\.\.", o)         # TLC never started: java or the jar is missing
    return Result(ok, fmt(c["claim"], item=item), why if ran else why + "\n" + o[-400:], category=None if ran else "toolchain_unavailable")


def k_regenerated(c, ctx):
    from workspace import sha
    before = {g: sha(ctx.root / g) for g in c["files"]}
    with tempfile.TemporaryDirectory() as td:
        for g in c["files"]: shutil.copy(ctx.root / g, pathlib.Path(td) / g.replace("/", "__"))
        ctx.sh(ctx.subst(c["command"]))
        drift = [g for g in c["files"] if not (ctx.root / g).exists() or sha(ctx.root / g) != before[g]]
        for g in c["files"]: shutil.copy(pathlib.Path(td) / g.replace("/", "__"), ctx.root / g)
    return Result(not drift, c["claim"], fmt(c.get("why"), drift=drift))


def k_manifest_choice(c, ctx):
    v = ctx.manifest.get(c["key"]) or c.get("default")
    return Result(v in c["choices"], fmt(c["claim"], value=v, note=c["choices"].get(v, "")), c.get("why"))


def k_manifest_commands(c, ctx):
    code, o = ctx.sh(c["item"])                            # as the manifest wrote it: supplementary, never blocking
    return Result(code == 0, c["claim"], o[-1200:])


def k_adapter(c, ctx):
    spec = importlib.util.spec_from_file_location("pack_adapter_" + re.sub(r"\W", "_", c["id"]), ctx.root / c["adapter"])
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    r = mod.run(ctx)
    return Result(not r["problems"], r["claim"], " | ".join(r["problems"]), outcome=r["status"],
                  outputs={k: r[k] for k in ("reviewer_context", "reviewer_flags") if k in r}, detail=r.get("detail"),
                  release_conditions=[tuple(x) for x in r.get("release_conditions", [])],
                  category=r.get("failure_category") or {"incomplete": "not_exercised"}.get(r["status"]), failing_contracts=list(r.get("failing") or []))


def k_attestation(c, ctx):
    import review as REV
    rf = c["required_from"]; ids = [e[rf["field"]] for e in yaml.safe_load((ctx.root / rf["yaml"]).read_text())[rf["list"]]]
    status, detail = REV.verify(ctx.review, ctx.reviewer_key, artifact_digest=ctx.artifact_digest, release_digest=ctx.release_digest, required_ids=ids)
    rc = ctx.outputs.get(c.get("reviewer_context_from"), {})
    flags = rc.get("reviewer_flags", [])
    return Result(True, f"{status} ({detail.get('reason') or detail.get('reviewer')})" + (f"; {len(flags)} wording flag(s) for reviewers" if flags else ""),
                  outcome=status, detail={"attestation": detail, **rc.get("reviewer_context", {})})


RUN = {"command": k_command, "files_present": k_files_present, "source_rules": k_source_rules, "tlc": k_tlc, "regenerated": k_regenerated,
       "manifest_choice": k_manifest_choice, "manifest_commands": k_manifest_commands, "adapter": k_adapter, "attestation": k_attestation}
