#!/usr/bin/env python3
"""
gate/packet.py — failure categories and the agent task packet. FROZEN. Domain-free.

Every failing check is put in one of six categories, so an agent (or a person) does not have to infer from a log
whether the fault is theirs, the toolchain's or the release's:

  violation               the implementation violates the contract: a check ran and found a counterexample
  not_exercised           the required behaviour was not exercised: a coverage obligation was not reached, or a
                          delivery check could not get the application to the state it needed
  evidence_missing        a file, artifact or attestation the evaluation needs is absent
  toolchain_unavailable   a tool the check declared (verifier, model checker, browser, runtime, package) is missing;
                          a blocker, never a pass, and not the candidate's code
  contract_change         the candidate changed, or asked for, something only a new release can change: a frozen file,
                          a manifest key or value the pack does not allow
  infrastructure          the evaluator, the release or the machine failed: an exception in the evaluator, a timeout,
                          a release whose own checks (proof, model, adequacy) fail, a seal or pin mismatch

The category is inferred, and says how (`category_basis`). Order: an exception or timeout in the evaluator; then a
declared tool recorded as unavailable or a tool the shell could not find; then the pack's own `failure_category` for
the check; then `about: release` (the check is about the pack, so its failure is the release's); then what the kind or
the delivery adapter reported; then the kind's default.

After every run the evaluator writes the task packet next to app-claims.json: task-packet.json (format
pith.task-packet/v1, schema gate/schemas/task-packet.schema.json) and TASK.md, the same content for reading. It is
small on purpose (a few KB): the state, the first blocking failure with its category, the contract records it bears
on, a minimal counterexample, what may and may not be edited, and the exact rerun commands. A small model can act
on it without reading the log.

    python3 gate/packet.py EVIDENCE_DIR [--json]      print the packet of a run (TASK.md, or the JSON)
    python3 gate/packet.py distill EVIDENCE_DIR [--policy-from RELEASE] [--json]
                                                      the distilled packet (below), recomputed from a run's evidence

Distilled packets (v0.13.0, docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 5). Every run also writes
task-packet.distilled.json and TASK.distilled.md: the same packet with `disclosure: redacted`, a structured
counterexample (`trace` of domain steps, `expected`, `observed`, `violated` records, `shrunk`) and every free-text
field passed through a redaction filter: no absolute host path, no Python or Node.js stack frame, and no identifier
defined in the release's own code (collected with ast) unless the pack's own documents use the word (its intent, the
documents its contract records cite, `packet.vocabulary`). A counterexample is read, in order, from a
`pith-counterexample: {json}` line a harness or verify step printed, from a model checker's state trace, from a
delivery adapter's per-workflow evidence, and from a migration report; a trace is truncated after its first diverging
step, and shrunk (gate/shrink.py) only against an offline oracle the pack declares (`traces.oracle`), never by
re-running the candidate. task-packet.json is unchanged for agents that hold the seed.
"""
import ast, json, pathlib, re, sys

FORMAT = "pith.task-packet/v1"
CATEGORIES = ("violation", "not_exercised", "evidence_missing", "toolchain_unavailable", "contract_change", "infrastructure")
KIND_DEFAULT = {"command": "violation", "files_present": "evidence_missing", "source_rules": "violation", "tlc": "violation",
                "regenerated": "violation", "manifest_choice": "contract_change", "manifest_commands": "violation", "adapter": "violation",
                "attestation": "evidence_missing"}
EVALUATOR_CHECKS = {"frozen files intact": "contract_change", "manifest allowlisted": "contract_change", "included paths": "contract_change",
                    "release seal": "infrastructure", "external release pin": "infrastructure", "pack well-formed": "infrastructure",
                    "judged copy unchanged": "infrastructure"}
UNAVAILABLE = ("not importable", "unknown", "unavailable", "")
TOOL_MISSING = [re.compile(p) for p in (r"command not found", r"(?m): not found$", r"No such file or directory: '[^']*'", r"Unable to access jarfile",
                                        r"Could not find or load main class", r"Executable doesn't exist", r"java: not found")]
NEXT = {
    "violation": "Change your own files (editable below) so the failing obligation holds. The counterexample is the smallest case "
                 "the checker found; reproduce it first, fix the cause, then rerun.",
    "not_exercised": "Your build never reached the behaviour this obligation needs, so it could not be judged. Make the model or "
                     "the application actually reach it (see the counterexample for what was missing); do not stub the check out.",
    "evidence_missing": "Add what is missing (named below) in your own files. Nothing was judged wrong yet; the evaluation cannot "
                        "proceed without it.",
    "toolchain_unavailable": "A tool the check needs is not available on this machine. This is not your code: install it (python3 gate/cli.py "
                             "doctor says how), then rerun. Never treat this as a pass.",
    "contract_change": "This needs a change to the contract, which you cannot make: restore any frozen file you edited, keep to the "
                       "manifest keys and values the pack allows, and report the change you need to the operator.",
    "infrastructure": "The evaluator, the release or the machine failed, not your code. Rerun once; if it fails the same way, report it "
                      "with this packet and do not change your code to work around it.",
}


def classify(name, kind, spec, res_category, why, toolchain, exc=None):
    """(category, basis) for a failed check. `spec` is the pack's check (None for the evaluator's own checks)."""
    why = why or ""
    if exc: return "infrastructure", f"the evaluator raised {exc} while running the check"
    if spec is None:
        cat = EVALUATOR_CHECKS.get(name, "infrastructure")
        return cat, {"contract_change": "the release or the manifest was changed in a way only the pack's maintainers may",
                     "infrastructure": "an evaluator check about the release or the run itself"}.get(cat, "")
    missing = [t for t in spec.get("tools", []) if str(toolchain.get(t, "")).strip() in UNAVAILABLE]
    if missing: return "toolchain_unavailable", f"declared tool(s) {missing} were recorded as unavailable"
    m = next((p.search(why) for p in TOOL_MISSING if p.search(why)), None)
    if m: return "toolchain_unavailable", f"the check's output says a tool is missing: {m.group(0)[:120]!r}"
    if spec.get("failure_category") in CATEGORIES: return spec["failure_category"], "declared by the pack for this check"
    if spec.get("about") == "release": return "infrastructure", "the check is about the release itself (the pack's own oracle), not the candidate"
    if res_category in CATEGORIES: return res_category, f"reported by the {kind} check"
    return KIND_DEFAULT.get(kind, "violation"), f"default for a failing {kind} check"


# ---------------------------------------------------------------- counterexamples (tool-specific, domain-free)
def counterexample(why, kind):
    """The smallest concrete failing case the tool printed, or None. Hypothesis shrinks, TLC searches breadth-first,
    pytest shows the failing test up to the failing line; each is kept short."""
    w = why or ""
    if "Falsifying example" in w:
        i = w.find("Falsifying example"); return {"source": "hypothesis (shrunk)", "text": _clip(w[i:], 1400)}
    if "The behavior up to this point is:" in w or (kind == "tlc" and "violated" in w):
        head = w.split("\n", 1)[0]; i = w.find("The behavior up to this point is:")
        return {"source": "tlc (shortest trace, breadth-first)", "text": _clip(head + ("\n" + _tlc_states(w[i:]) if i >= 0 else ""), 1400)}
    t = _pytest_first(w)
    if t: return {"source": "pytest (first failing test, up to the failing line)", "text": _clip(t, 1400)}
    errs = [l.strip() for l in w.splitlines() if re.search(r"\b[Ee]rror\b", l)][:6]
    return {"source": "tool output (error lines)", "text": _clip("\n".join(errs), 900)} if errs else None


def _tlc_states(s):
    out = []
    for block in re.split(r"\n(?=State \d+:)", s)[1:9]:
        out.append("\n".join(l for l in block.splitlines() if l.strip())[:300])
    return "\n".join(out)


def _pytest_first(w):
    m = re.search(r"_{3,} (\S+) _{3,}\n(.*?)(?=\n_{3,} |\n={3,} short test summary|\Z)", w, re.S)
    if not m: return None
    body = m.group(2).splitlines()
    src = [l for l in body if l.startswith("    ") or l.startswith(">")]
    k = next((i for i, l in enumerate(src) if l.startswith(">")), len(src) - 1)
    errs = [l for l in body if l.startswith("E ")][:8]
    loc = next((l for l in body if re.match(r"^\S+\.py:\d+: ", l)), "")
    return f"test {m.group(1)}\n" + "\n".join(src[max(0, k - 12):k + 1]) + ("\n" + "\n".join(errs) if errs else "") + (f"\n{loc}" if loc else "")


def _clip(s, n): s = s.strip(); return s if len(s) <= n else s[:n - 20] + "\n… (truncated)"


# ---------------------------------------------------------------- the packet
def contracts_for(rec, P, text):
    """The contract records a failed check bears on: ids the failing output or the adapter names, among the records the
    check verifies or establishes; else all of those, marked as such."""
    group = rec["id"].split("/")[0]
    related = [c for c in P.get("contracts", []) if group in c.get("verified_by", []) or c["id"] in rec.get("establishes", [])]
    named = [c for c in related if c["id"] in (rec.get("failing_contracts") or [])
             or re.search(rf"(?<![\w-]){re.escape(c['id'])}(?![\w-])", text or "")]
    basis = "named by the failing output" if named else ("records this check verifies (the failing output names none)" if related else "none recorded")
    pick = named or related
    return [{"id": c["id"], "intent": c.get("intent"), "semantics": c.get("semantics"), "change": c.get("change")} for c in pick[:8]], basis


def build(claims, records, P, mode, candidate, policy_src, out, toolchain, release_digest):
    statuses = [s for s in (P.get("statuses") or {})]
    failed = [r for r in records if r["result"] == "fail"]
    first = next((r for r in failed if r.get("blocking", True)), None) or (failed[0] if failed else None)
    completion = P.get("completion_status")
    state = "refused" if (first and first.get("blocking", True)) else ("failing" if failed else "done")
    pending = [m for m in claims.get("release_ready_missing", [])]
    owned = (P.get("candidate") or {}).get("owned_dirs", [])
    py = "python3"
    if mode == "authoritative":
        rerun = f"{py} -I {policy_src}/gate/app_gate.py --candidate {candidate} --out <fresh dir> --expected-release {release_digest} --reuse {out}"
    else:
        rerun = f"{py} gate/app_gate.py --out <fresh dir> --reuse {out}"
    pk = {"format": FORMAT, "pack": claims.get("pack") or {k: P["pack"].get(k) for k in ("id", "version", "contract_version")}, "release_digest": release_digest, "artifact_digest": claims.get("artifact_digest"),
          "gate_mode": mode, "state": state, "statuses": {s: claims.get(s) for s in statuses},
          "done_when": f"{completion} is ready" + "".join(f"; {s} ready" for s in statuses if s != completion and (P['statuses'][s].get('ready') or {}).get('startswith')),
          "first_failure": None, "other_failures": [], "not_yours": [], "coverage": claims.get("coverage"),
          "editable": {"dirs": owned + list((claims.get("coverage") or {}).get("included") or []), "manifest": "app.manifest.yaml",
                       "manifest_keys": (P.get("candidate") or {}).get("manifest_allowlist", [])},
          "frozen": ["gate/", "pack.yaml"] + [d + "/" for d in P.get("policy_dirs", [])],
          "rerun": {"full": rerun, "focused": None,
                    "impact": f"{py} gate/evidence.py impact --evidence {out}" + (f" --candidate {candidate} --policy-from {policy_src}" if mode == "authoritative" else "")},
          "evidence": {"claims": str(pathlib.Path(out) / "app-claims.json"), "records": str(pathlib.Path(out) / "evidence.json")}}
    if first:
        cx = counterexample(first.get("why"), first.get("kind"))
        cons, basis = contracts_for(first, P, (first.get("why") or "") + "\n" + ((cx or {}).get("text") or ""))
        pk["first_failure"] = {"check": first["id"], "name": first["check"], "area": first.get("area"), "kind": first.get("kind"),
                               "method": first.get("method"), "category": first.get("category"), "category_basis": first.get("category_basis"),
                               "blocking": first.get("blocking", True), "contracts": cons, "contracts_basis": basis,
                               "counterexample": cx, "why": _clip(first.get("why") or "", 1200), "next": NEXT.get(first.get("category"), "")}
        f = focused(first, P, cx)
        pk["rerun"]["focused"] = f and f"cd {candidate} && {f}"
    pk["other_failures"] = [{"check": r["id"], "category": r.get("category"), "why": _clip(r.get("why") or "", 240)} for r in failed if r is not first][:6]
    human = {s for s, d in (P.get("statuses") or {}).items() if d.get("rule") == "from_check" and
             next((c for c in P.get("checks", []) if c["id"] == d.get("check")), {}).get("kind") == "attestation"}
    pk["not_yours"] = [m for m in pending if m in human or m in ("gate_mode", "authority", "isolation", "browser")]
    if state == "done":
        pk["next"] = "Done for you: every status you can affect is at its required value. " + \
                     (f"Still pending and not yours to produce: {pk['not_yours']}." if pk["not_yours"] else "")
    elif first and not first.get("blocking", True):
        pk["next"] = "No blocking refusal; the first non-blocking failure below decides whether you are done."
    return pk


def focused(rec, P, cx):
    """A faster way to reproduce the first failure in a checkout that holds the release (a seed checkout does):
    the failing pytest test alone. Advisory: only the full run decides."""
    if rec.get("kind") != "command" or not cx or not cx["source"].startswith("pytest"): return None
    m = re.match(r"test (\S+)", cx["text"]); spec = next((c for c in P.get("checks", []) if c["id"] == rec["id"].split("/")[0]), {})
    cmd = spec.get("command", "")
    if "{pytest}" not in cmd or not m: return None
    pytest = (P.get("pytest") or "{python} -m pytest -q").replace("{python}", "python3").replace(" --rootdir={root}", "")
    return cmd.replace("{pytest}", pytest).replace("{python}", "python3") + f" -k {m.group(1).split('[')[0]}"


def markdown(pk):
    L = [f"# Task packet: {pk['state'].upper()}", "",
         f"Pack {pk['pack']['id']} {pk['pack']['version']}, release {pk['release_digest'][:16] or '(not computed)'}, artifact {pk['artifact_digest'][:16]}, {pk['gate_mode']} run.",
         "Statuses: " + ("; ".join(f"{s} = {str(v).split(';')[0]}" for s, v in pk["statuses"].items() if v is not None) or "not evaluated") + f". Done when {pk['done_when']}.", ""]
    f = pk["first_failure"]
    if f:
        L += [f"## First {'refusal' if f['blocking'] else 'failure'}: {f['name']} ({f['check']})", "",
              f"Category: **{f['category']}** ({f['category_basis']}).", "", f["next"], ""]
        if f["contracts"]:
            L += [f"Contract records ({f['contracts_basis']}):"] + [f"- {c['id']}: {c['intent']}" + (f" [{c['change']}]" if c.get("change") else "") for c in f["contracts"]] + [""]
        if f["counterexample"]:
            L += [f"Counterexample ({f['counterexample']['source']}):", "", "```", f["counterexample"]["text"], "```", ""]
        elif f["why"]:
            L += ["Why:", "", "```", f["why"], "```", ""]
    elif pk.get("next"):
        L += [pk["next"], ""]
    if pk["other_failures"]:
        L += ["Other failures: " + "; ".join(f"{o['check']} ({o['category']})" for o in pk["other_failures"]), ""]
    if pk["not_yours"]: L += [f"Pending, not yours to produce: {', '.join(pk['not_yours'])}.", ""]
    if pk.get("coverage"): L += [f"Coverage: {pk['coverage']['statement']}", ""]
    L += [f"You may edit: {', '.join(d + '/' for d in pk['editable']['dirs'])} and {pk['editable']['manifest']} (keys {pk['editable']['manifest_keys']}).",
          f"Frozen (editing any of it is refused): {', '.join(pk['frozen'])}.", "",
          "Rerun:", "", "```", pk["rerun"]["full"]] + ([pk["rerun"]["focused"] + "    # faster, advisory: the failing test alone"] if pk["rerun"]["focused"] else []) + \
         [pk["rerun"]["impact"] + "    # what your edit invalidates", "```", ""]
    return "\n".join(L)


def write(out, pk):
    (pathlib.Path(out) / "task-packet.json").write_text(json.dumps(pk, indent=1))
    (pathlib.Path(out) / "TASK.md").write_text(markdown(pk))


# ---------------------------------------------------------------- distilled packets (v0.13.0)
CX_LINE = re.compile(r"pith-counterexample:\s*(\{.*\})")
PATH = re.compile(r"""(?<![\w./-])(?:file://)?(?:/(?:Users|home|private|var|tmp|opt|Library|root|usr|etc|mnt|srv|workspace|candidate|evidence|pith|src|app)\b|[A-Za-z]:\\)[^\s'"`),\]]*""")
FRAME_LINES = [re.compile(p) for p in (r'^\s*File "[^"]*", line \d+', r"^\s*Traceback \(most recent call last\)", r"^\s*\S+\.(py|mjs|js|cjs|ts):\d+(:\d+)?:?",
                                         r"^\s*at (?:async )?\S.*\(?\S+:\d+:\d+\)?\s*$", r"^\s*\^+\s*$", r"^\s*~*\^+~*\s*$", r"^\s*node:internal")]
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PROTOCOL_WORDS = {"step", "action", "args", "observed", "expected", "violated", "source", "trace", "state", "shrunk", "against", "oracle",
                  "from_steps", "to_steps", "diverged_at", "redacted", "text", "true", "false", "null", "none", "None", "True", "False"}


def cx_line(steps, expected=None, observed=None, violated=(), diverged_at=None, replayable=False, source="harness"):
    """The one line a harness (or a migration's verify step) puts in a failing assertion's message so that the packet
    can carry its counterexample as domain steps: steps are [{"step", "action", "args", "observed", "expected"?}] in the
    contract's own words. `replayable`: the steps can be replayed through the pack's offline oracle (traces.oracle)."""
    X = {"source": source, "steps": list(steps), "expected": expected, "observed": observed, "violated": list(violated), "replayable": bool(replayable)}
    if diverged_at is not None: X["diverged_at"] = diverged_at
    return "pith-counterexample: " + json.dumps(X, sort_keys=True, separators=(",", ":"), default=str)


def vocabulary(root, P):
    """(allowed words, identifiers of the release's own code). Allowed: every word in the pack's intent document, in the
    documents its contract records cite (markdown, yaml, TLA+, Dafny, JSON schema) and in `packet.vocabulary`, plus the
    record and check ids. Code identifiers: every name a Python module of the release (gate/ and the policy dirs) defines."""
    root = pathlib.Path(root); docs = set(); allowed = set(PROTOCOL_WORDS)
    if (P.get("pack") or {}).get("intent"): docs.add(str(P["pack"]["intent"]).split("/", 2)[-1] if not (root / P["pack"]["intent"]).exists() else P["pack"]["intent"])
    for c in P.get("contracts", []):
        allowed.add(c["id"])
        for v in (c.get("semantics") or {}).values():
            f = str(v).split()[0].split("#")[0]
            if not f.endswith((".py", ".mjs", ".js")): docs.add(f)
    docs |= set(((P.get("packet") or {}).get("vocabulary")) or [])
    for c in P.get("preflight", []) + P.get("checks", []): allowed |= {c["id"], *re.split(r"[./]", c["id"])}
    for d in docs:
        f = root / d
        if f.is_file(): allowed |= set(WORD.findall(f.read_text(errors="ignore")))
    allowed |= set(WORD.findall(json.dumps([c.get("intent") for c in P.get("contracts", [])])))
    code = set()
    for d in ["gate"] + list(P.get("policy_dirs", [])):
        for f in (root / d).rglob("*.py") if (root / d).is_dir() else []:
            try: tree = ast.parse(f.read_text(errors="ignore"))
            except SyntaxError: continue
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): code.add(n.name)
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store): code.add(n.id)
                elif isinstance(n, ast.arg): code.add(n.arg)
                elif isinstance(n, ast.alias): code.add((n.asname or n.name).split(".")[0])
    return allowed, {w for w in code if code_shaped(w) and w not in allowed}


def code_shaped(w):
    """A name only code produces: snake_case, camelCase or with digits inside. A plain word ("found", "rows") reads as
    prose wherever it appears, so it is not masked even when some module also uses it as a name."""
    return len(w) > 2 and ("_" in w.strip("_") or re.search(r"[a-z][A-Z]", w) is not None or re.search(r"[A-Za-z]\d", w) is not None)


def redact(text, code, limit=1200):
    """Text with stack frames removed, absolute paths replaced by «path» and the release's code identifiers by «code»."""
    if not text: return ""
    lines = []; src = str(text).splitlines()
    pytest_echo = any(l.startswith("E ") for l in src)               # pytest echoes the judge's own source before its E lines
    skip_next = False
    for l in src:
        if skip_next and l.startswith("    "): skip_next = False; continue
        skip_next = False
        if any(p.search(l) for p in FRAME_LINES): skip_next = l.lstrip().startswith("File "); continue
        if pytest_echo and (l.startswith(">") or (l[:1].isspace() and not l.startswith("E ")) or re.match(r"^test \S+$", l)): continue
        if l.startswith("E "): l = l[1:].strip()
        if not l.strip() or l.strip() in ("Use -v to get more diff",) or l.strip().startswith(("Omitting ", "Full diff", "Use -v")): continue
        if re.match(r"^(={3,}|_{3,}|-{3,})", l.strip()) or re.match(r"^(FAILED|ERROR|PASSED|SKIPPED|XFAIL|XPASS) \S", l.strip()): continue
        if re.match(r"^[.FEsxX]+\s*(\[\s*\d+%\])?$", l.strip()) or re.match(r"^\d+ (passed|failed|error)", l.strip()): continue
        if "pith-counterexample:" in l: continue                     # carried structured in the counterexample, never as text
        l = re.sub(r"<[\w.]+ object at 0x[0-9a-fA-F]+>", "<object>", l)
        lines.append(l)
    t = PATH.sub("«path»", "\n".join(lines))
    t = WORD.sub(lambda m: "«code»" if m.group(0) in code else m.group(0), t)
    t = re.sub(r"(«code»[\s.,:()\[\]]*){2,}", "«code» ", t)
    return _clip(re.sub(r"\n{3,}", "\n\n", t).strip(), limit)


def _clip_middle(s, n):
    """Keep the head and the tail (where a trace's diverging step is), drop the middle."""
    s = s.strip()
    if len(s) <= n: return s
    keep = n - 40; return s[:keep // 3] + "\n… (steps omitted) …\n" + s[-(keep - keep // 3):]


def _scrub(o, code):
    if isinstance(o, str): return redact(o, code, 400)
    if isinstance(o, list): return [_scrub(x, code) for x in o]
    if isinstance(o, dict): return {k: _scrub(v, code) for k, v in o.items()}
    return o


def _tlc_trace(text):
    steps = []
    for n, block in enumerate(re.split(r"\n(?=State \d+:)", text)[1:], 1):
        head, *rest = block.splitlines()
        m = re.match(r"State (\d+):\s*<?([A-Za-z_][\w]*)?", head)
        action = (m.group(2) if m and m.group(2) and m.group(2) not in ("Initial",) else ("initial state" if "Initial" in head else None))
        state = {}
        for l in rest:
            v = re.match(r"^\s*/\\\s*(\w+)\s*=\s*(.*)$", l)
            if v: state[v.group(1)] = v.group(2).strip()[:200]
        steps.append({"step": n, "action": action, "state": state})
    return steps


def structured(first, claims, P, root):
    """A structured counterexample for the first failure (None when nothing structured can be read)."""
    why = first.get("why") or ""
    m = CX_LINE.search(why)
    if m:
        try:
            X = json.loads(m.group(1)); X.setdefault("source", "harness counterexample"); return X
        except ValueError: pass
    if first.get("kind") == "tlc" or "The behavior up to this point is:" in why:
        v = re.search(r"(?:Invariant|Action property|Temporal property) (\S+) is violated", why)
        steps = _tlc_trace(why[why.find("The behavior up to this point is:"):]) if "The behavior up to this point is:" in why else []
        return {"source": "model checker (shortest trace, breadth-first)", "trace": steps, "violated_property": v and v.group(1)} if (steps or v) else None
    D = claims.get((next((c for c in P.get("checks", []) if c["id"] == first.get("check")), {}) or {}).get("claims_key") or "", {}) or {}
    bad = {k: w for k, w in (D.get("workflows") or {}).items() if not w.get("ok")}
    if bad:
        trace = []
        for k, w in bad.items():
            for e in w.get("evidence") or []:
                for part in re.split(r";\s*(?:then\s+)?", str(e)):
                    if part.strip(): trace.append({"step": len(trace) + 1, "workflow": k, "action": part.strip()[:300]})
        return {"source": "delivery workflows", "violated": sorted(bad), "trace": trace[:24]}
    return None


def shrink_trace(X, P, root):
    """Truncate after the first diverging step; shrink against the pack's offline oracle when it declares one."""
    steps = X.get("steps")
    if not isinstance(steps, list) or not steps: return X
    k = X.get("diverged_at", len(steps) - 1)
    if isinstance(k, int) and 0 <= k < len(steps) - 1:
        X["shrunk"] = {"from_steps": len(steps), "to_steps": k + 1, "against": "truncated after the first diverging step"}; steps = steps[:k + 1]
    cmd = ((P.get("traces") or {}).get("oracle"))
    if cmd and X.get("replayable", False) and len(steps) > 1:
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import shrink as SH
            cmd = cmd.replace("{python}", sys.executable)
            want = SH.oracle(cmd, steps, cwd=root)[-1]
            small, calls = SH.ddmin(steps, lambda s: SH.oracle(cmd, s, cwd=root)[-1] == want, keep_last=True)
            if len(small) < len(steps):
                X["shrunk"] = {"from_steps": len(X["steps"]), "to_steps": len(small), "against": "oracle", "oracle_calls": calls}; steps = small
        except Exception as e:
            X.setdefault("notes", []).append(f"not shrunk against the oracle: {type(e).__name__}")
    X["steps"] = [dict(st, step=i + 1) if isinstance(st, dict) else st for i, st in enumerate(steps)]
    if "diverged_at" in X or X.get("shrunk"): X["diverged_at"] = len(steps) - 1
    return X


def distill(pk, claims, P, root):
    """The redacted, structured packet (format unchanged, `disclosure: redacted`)."""
    allowed, code = vocabulary(root, P)
    D = {k: v for k, v in pk.items() if k not in ("rerun", "evidence", "first_failure", "other_failures")}
    D["disclosure"] = "redacted"
    D["rerun"] = {"full": "rerun the judge as you did (a fresh --out directory; --reuse this run's evidence)", "focused": None,
                  "impact": "gate/evidence.py impact --evidence <this run's evidence>"}
    D["evidence"] = {"claims": "app-claims.json", "records": "evidence.json"}
    if pk.get("coverage"): D["coverage"] = {**pk["coverage"], "judged_paths": [p for p in pk["coverage"].get("judged_paths", []) if not PATH.match(str(p))]}
    f = pk.get("first_failure")
    if f:
        first = next((r for r in claims.get("checks", []) if r.get("id") == f["check"]), {}) or {}
        X = structured({**first, "kind": f.get("kind"), "check": f["check"]}, claims, P, root)
        X = shrink_trace(X, P, root) if X else None
        cons = [{"id": c["id"], "intent": c.get("intent"), "change": c.get("change"),
                 "semantics": {k: v for k, v in (c.get("semantics") or {}).items() if not str(v).split()[0].endswith((".py", ".mjs", ".js"))}} for c in f.get("contracts", [])]
        cx = None
        if X:
            cx = {"source": X.get("source", "counterexample"), "text": _clip_middle(redact(_cx_text(X), code, 100000), 1400), "redacted": True,
                  **{k: _scrub(X[k], code) for k in ("trace", "steps", "expected", "observed", "violated", "violated_property", "shrunk", "diverged_at") if k in X}}
            if "steps" in cx and "trace" not in cx: cx["trace"] = cx.pop("steps")
        elif f.get("counterexample"):
            cx = {"source": f["counterexample"]["source"], "text": redact(f["counterexample"]["text"], code, 1400), "redacted": True}
        D["first_failure"] = {**{k: f.get(k) for k in ("check", "name", "area", "kind", "method", "category", "category_basis", "blocking", "contracts_basis", "next")},
                              "contracts": cons, "counterexample": cx, "why": redact(f.get("why"), code, 600 if X else 900)}
    else:
        D["first_failure"] = None
    D["other_failures"] = [{"check": o["check"], "category": o.get("category"), "why": redact(o.get("why"), code, 240)} for o in pk.get("other_failures", [])]
    return D


def _cx_text(X):
    L = []
    for s in X.get("trace") or X.get("steps") or []:
        if not isinstance(s, dict): L.append(str(s)); continue
        bits = [f"Step {s.get('step', len(L) + 1)}:"] + [f"{s[k]}" for k in ("workflow", "action") if s.get(k)]
        if s.get("args") is not None: bits.append(json.dumps(s["args"], sort_keys=True))
        if "observed" in s: bits.append(f"-> observed {json.dumps(s['observed'], sort_keys=True)}")
        if "expected" in s: bits.append(f"(expected {json.dumps(s['expected'], sort_keys=True)})")
        if s.get("state"): bits.append(" ".join(f"{k}={v}" for k, v in s["state"].items()))
        L.append(" ".join(bits))
    if "expected" in X or "observed" in X: L.append(f"Expected {json.dumps(X.get('expected'), sort_keys=True)}; observed {json.dumps(X.get('observed'), sort_keys=True)}.")
    if X.get("violated") or X.get("violated_property"): L.append(f"Violates {X.get('violated') or X.get('violated_property')}.")
    return "\n".join(L)


def write_distilled(out, pk, claims, P, root):
    D = distill(pk, claims, P, root)
    (pathlib.Path(out) / "task-packet.distilled.json").write_text(json.dumps(D, indent=1))
    (pathlib.Path(out) / "TASK.distilled.md").write_text(markdown(D))
    return D


def main():
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "distill":
        ev = pathlib.Path(a[1]); pol = pathlib.Path(a[a.index("--policy-from") + 1]) if "--policy-from" in a else pathlib.Path(__file__).resolve().parent.parent
        import yaml
        P = yaml.safe_load((pol / "pack.yaml").read_text()); pk = json.loads((ev / "task-packet.json").read_text())
        claims = json.loads((ev / "app-claims.json").read_text()) if (ev / "app-claims.json").exists() else {}
        D = write_distilled(ev, pk, claims, P, pol)
        print(json.dumps(D, indent=1) if "--json" in a else markdown(D)); return
    pk = json.loads((pathlib.Path(a[0]) / "task-packet.json").read_text())
    print(json.dumps(pk, indent=1) if "--json" in a else markdown(pk))


if __name__ == "__main__":
    main()
