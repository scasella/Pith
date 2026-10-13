#!/usr/bin/env python3
"""
gate/compose.py — composition contracts. FROZEN. Domain-free.

A composition contract (`composition.yaml`, format pith.composition/v1) names the components of a workflow, the state
each one owns, the effects through which that state may change, each component's local invariants, the invariants
that span components, the transitions that must be atomic and the assumptions between components. The model is TLA+
in its native form: one module per component, an integration module, and a contract module that extends the
integration and states the shared invariants.

    python3 gate/compose.py check DIR [--integration MODULE_FILE] [--json]

`check` establishes, by model checking within the model's bounds:
  1. structure: every component declares exactly the variables it owns, no variable has two owners, every shared
     invariant spans at least two components, atomicity and known-wrong entries name what exists;
  2. the integration (model/ or --integration) keeps every local invariant and every permitted-effect rule (owned
     state changes only through the owner's declared effects), and every shared invariant;
  3. every known-wrong integration keeps the local invariants and effect rules and violates exactly the shared
     invariants it is listed for — so the check can tell a broken composition from a broken component.
Exit 0 when all hold. The joint result is only as strong as the atomicity assumptions; the report repeats them.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile
import yaml

FORMAT = "pith.composition/v1"


def problems(C, d):
    out = []
    if C.get("format") != FORMAT: out.append(f"format is not {FORMAT}")
    comps = C.get("components") or []
    ids = [c.get("id") for c in comps]
    if len(comps) < 2: out.append("a composition needs at least two components")
    if len(set(ids)) != len(ids): out.append("duplicate component ids")
    owner = {}
    for c in comps:
        for k in ("id", "module", "owns", "invariants", "effects"):
            if not c.get(k): out.append(f"component {c.get('id')}: missing {k}")
        mod = d / C["model"]["dir"] / f"{c.get('module')}.tla"
        if not mod.is_file(): out.append(f"component {c.get('id')}: {mod.relative_to(d)} does not exist"); continue
        declared = set()
        for m in re.finditer(r"^\s*VARIABLES?\s+([^\n\\]+)", mod.read_text(), re.M): declared |= {v.strip() for v in m.group(1).split(",") if v.strip()}
        if declared != set(c.get("owns") or []): out.append(f"component {c['id']}: module declares {sorted(declared)}, owns lists {sorted(c.get('owns') or [])}")
        for v in c.get("owns") or []:
            if v in owner: out.append(f"variable {v} is owned by both {owner[v]} and {c['id']}")
            owner[v] = c["id"]
    for s in C.get("shared_invariants") or []:
        if len(set(s.get("components") or [])) < 2: out.append(f"shared invariant {s.get('id')}: spans fewer than two components (a local invariant belongs to its component)")
        for x in s.get("components") or []:
            if x not in ids: out.append(f"shared invariant {s.get('id')}: unknown component {x}")
    if not C.get("shared_invariants"): out.append("no shared invariants: nothing about the composition is claimed")
    for a in C.get("atomicity") or []:
        for x in a.get("components") or []:
            if x not in ids: out.append(f"atomicity {a.get('transition')}: unknown component {x}")
    shared = {s.get("id") for s in C.get("shared_invariants") or []}
    if not C.get("wrong"): out.append("no known-wrong integration: nothing shows the shared invariants can fail")
    for w in C.get("wrong") or []:
        if not (d / w.get("dir", "")).is_dir(): out.append(f"wrong {w.get('dir')}: not a directory")
        if not set(w.get("violates") or []) <= shared or not w.get("violates"): out.append(f"wrong {w.get('dir')}: violates must name shared invariants")
    if not C.get("assumptions"): out.append("no assumptions stated")
    return out


def tlc(C, d, integration, invariants, properties):
    """Model-check the contract module with `integration` (a file) as the integration module. Returns (ok, violated, output)."""
    m = C["model"]; work = pathlib.Path(tempfile.mkdtemp(prefix="compose-"))
    try:
        for f in (d / m["dir"]).glob("*.tla"): shutil.copy(f, work)
        if integration: shutil.copy(integration, work / f"{m['integration']}.tla")
        owned = {c["id"]: c for c in C["components"]}
        effects = "\n".join(f"Effects_{i} == [][ " + " \\/ ".join(f"({e})" for e in c["effects"]) + f" ]_<<{', '.join(c['owns'])}>>" for i, c in owned.items())
        (work / "MCCompose.tla").write_text(f"---- MODULE MCCompose ----\nEXTENDS {m['contract']}\n{effects}\n====\n")
        consts = "\n".join(f"  {k} = {v}" for k, v in m.get("constants", {}).items())
        (work / "MCCompose.cfg").write_text(f"CONSTANTS\n{consts}\nSPECIFICATION Spec\n" + "".join(f"INVARIANT {i}\n" for i in invariants) + "".join(f"PROPERTY {p}\n" for p in properties))
        jar = os.environ.get("TLA2TOOLS", "tla2tools.jar")
        r = subprocess.run(["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-nowarning", "-workers", "2", "-deadlock", "-config", "MCCompose.cfg", "MCCompose"], cwd=work, capture_output=True, text=True, timeout=900)
        o = r.stdout + r.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not re.search(r"TLC2 Version|Starting\.\.\.", o): return None, None, o[-600:]
    v = re.search(r"(?:Invariant|Temporal property|Action property) (\S+) is violated", o)
    return "No error has been found" in o, (v.group(1) if v else None), o


def check(d, integration=None):
    d = pathlib.Path(d).resolve(); C = yaml.safe_load((d / "composition.yaml").read_text())
    rep = {"format": "pith.composition-report/v1", "composition": C.get("id"), "version": C.get("version"), "runs": [], "assumptions": C.get("assumptions", []), "atomicity": C.get("atomicity", [])}
    rep["problems"] = problems(C, d)
    if rep["problems"]: rep["ok"] = False; return rep
    local = [i for c in C["components"] for i in c["invariants"]]; eff = [f"Effects_{c['id']}" for c in C["components"]]
    shared = [s["id"] for s in C["shared_invariants"]]

    def run(label, integ, invs, props, want_ok, want_violated=None):
        ok, violated, out = tlc(C, d, integ, invs, props)
        if ok is None: passed, why = False, "TLC did not run (java or TLA2TOOLS unavailable): " + out[-300:]
        elif want_ok: passed, why = bool(ok), ("holds" if ok else f"violated: {violated or 'see output'}")
        else: passed, why = (not ok and violated == want_violated), (f"violated: {violated}" if not ok else "holds (expected a violation)")
        rep["runs"].append({"run": label, "invariants": invs, "properties": props, "result": "pass" if passed else "fail", "detail": why,
                            **({"counterexample": _trace(out)} if ok is False else {})})
        return passed

    cand = pathlib.Path(integration).resolve() if integration else None
    run("integration: local invariants, permitted effects, shared invariants", cand, local + shared, eff, True)
    for w in C["wrong"]:
        f = d / w["dir"] / f"{C['model']['integration']}.tla"
        run(f"known-wrong {w['dir']}: local invariants and permitted effects hold", f, local, eff, True)
        for s in shared:
            if s in w["violates"]: run(f"known-wrong {w['dir']}: {s} is violated", f, [s], [], False, s)
            else: run(f"known-wrong {w['dir']}: {s} holds", f, [s], [], True)
    rep["ok"] = all(r["result"] == "pass" for r in rep["runs"])
    return rep


def _trace(o):
    m = re.search(r"Error: .*?is violated.*?(?=\n\d+ states generated|\nThe number of states|\Z)", o, re.S)
    return (m.group(0) if m else o[-800:])[:1500]


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("dir"); c.add_argument("--integration"); c.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = check(a.dir, a.integration)
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for p in rep["problems"]: print(f"[ERROR] {p}")
        for r in rep["runs"]: print(f"[{'PASS' if r['result'] == 'pass' else 'FAIL'}] {r['run']} — {r['detail']}")
        print(f"composition {rep['composition']}: {'ok' if rep['ok'] else 'NOT ok'}; holds under the assumptions: " + "; ".join(rep["assumptions"]))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
