#!/usr/bin/env python3
"""
harness/refines.py — the reference model IS the TLA+ spec, within the model's bounds. FROZEN.

    TLA2TOOLS=tla2tools.jar python3 harness/refines.py

Runs TLC on model/MC.tla with `-dump dot,actionlabels` to get the complete reachable state graph of the spec, builds
the reachable graph of harness/reference.py from the same configuration (actors, roles, quorum, MaxRev from
model/MC.tla and model/MC.cfg), and compares: the same initial states, the same reachable states, and for every
state the same set of (action, successor) pairs. Every state includes the model's history variable `last` (who did
the step that produced it), so two models that reach the same document by different actors are told apart: a
reference that lets the wrong actor reject, publish, submit or edit fails here. Exit 0 iff identical. This turns "the service is tested against a
Python model" into "the service is tested against the spec, exhaustively equivalent within these bounds"; outside
the bounds (more revisions, more actors) the equivalence is by construction of the same rules, not checked.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from harness import reference as R


def tla_value(s, i=0):
    """Parse the TLC value syntax the dump uses (strings, integers, booleans, <<tuples>>, {sets}, [records]) -> (value, next index)."""
    def ws(i):
        while i < len(s) and s[i] in " \n\t": i += 1
        return i
    i = ws(i)
    if s[i] == '"':
        j = s.index('"', i + 1); return s[i + 1:j], j + 1
    if s.startswith("<<", i):
        out, i = [], ws(i + 2)
        while not s.startswith(">>", i):
            v, i = tla_value(s, i); out.append(v); i = ws(i)
            if s[i] == ",": i = ws(i + 1)
        return tuple(out), i + 2
    if s[i] == "{":
        out, i = [], ws(i + 1)
        while s[i] != "}":
            v, i = tla_value(s, i); out.append(v); i = ws(i)
            if s[i] == ",": i = ws(i + 1)
        return frozenset(out), i + 1
    m = re.match(r"-?\d+|TRUE|FALSE", s[i:])
    if m: t = m.group(0); return ({"TRUE": True, "FALSE": False}.get(t, int(t) if t[-1].isdigit() else t)), i + len(t)
    raise ValueError(f"unparsed TLC value at {s[i:i + 40]!r}")


def tlc_graph(jar):
    work = pathlib.Path(tempfile.mkdtemp())
    for f in (ROOT / "model").iterdir():
        if f.suffix in (".tla", ".cfg"): (work / f.name).write_bytes(f.read_bytes())
    r = subprocess.run(["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-nowarning", "-deadlock", "-workers", "1", "-dump", "dot,actionlabels", "graph", "-config", "MC.cfg", "MC.tla"],
                       cwd=work, capture_output=True, text=True)
    try:
        if "No error has been found" not in r.stdout: sys.exit("TLC did not complete cleanly:\n" + r.stdout[-1500:])
        dot = next(work.glob("graph*")).read_text()
    finally: shutil.rmtree(work, ignore_errors=True)
    nodes, init, edges = {}, set(), set()
    for m in re.finditer(r'^(-?\d+) \[label="((?:[^"\\]|\\.)*)"(,style = filled)?\]', dot, re.M):
        label = m.group(2).replace("\\\\", "\\").replace('\\"', '"').replace("\\n", "\n")
        st = {}
        for part in label.split("/\\")[1:]:
            k, v = part.split("=", 1); st[k.strip()] = tla_value(v.strip())[0]
        key = (st["status"], st["rev"], tuple(a for a in st["author"] if a != "none"), frozenset(st["approvals"]), tuple(st["last"]))
        nodes[m.group(1)] = key
        if m.group(3): init.add(key)
    for m in re.finditer(r'^(-?\d+) -> (-?\d+) \[label="(\w+)"', dot, re.M):
        edges.add((nodes[m.group(1)], m.group(3), nodes[m.group(2)]))
    return set(nodes.values()), init, edges


def mc_config():
    mc = (ROOT / "model/MC.tla").read_text(); cfg = (ROOT / "model/MC.cfg").read_text()
    sets = {k: set(re.findall(r'"(\w+)"', v)) for k, v in re.findall(r"^MC(\w+)\s*==\s*\{([^}]*)\}", mc, re.M)}
    nums = {k: int(v) for k, v in re.findall(r"^\s*(Quorum|MaxRev)\s*=\s*(\d+)", cfg, re.M)}
    roles = {a: tuple(r for r, s in (("editor", "Editors"), ("approver", "Approvers"), ("publisher", "Publishers")) if a in sets[s]) for a in sets["Actors"]}
    return sets["Actors"], roles, nums["Quorum"], nums["MaxRev"]


def reference_graph():
    actors, roles, quorum, max_rev = mc_config()
    key = lambda d: (d.status, d.rev, d.authors, d.approvals, d.last)       # last: who did the step, so actors are compared too
    init = {key(R.create(a, roles)[1]) for a in actors if R.create(a, roles)[0] is None}
    seen, edges, todo = set(init), set(), [R.create(a, roles)[1] for a in actors if R.create(a, roles)[0] is None]
    label = {"edit": "Edit", "submit": "Submit", "approve": "Approve", "reject": "Reject", "publish": "Publish"}
    while todo:
        d = todo.pop()
        for op in label:
            for a in actors:
                for r in ([None] if op == "edit" else range(1, max_rev + 1)):
                    why, d2 = R.step(d, op, a, roles, r, quorum=quorum, max_rev=max_rev)
                    if why is None:
                        edges.add((key(d), label[op], key(d2)))
                        if key(d2) not in seen: seen.add(key(d2)); todo.append(d2)
    return seen, init, edges


def main():
    jar = os.environ.get("TLA2TOOLS", "tla2tools.jar")
    ts, ti, te = tlc_graph(jar); rs, ri, re_ = reference_graph()
    problems = []
    if ti != ri: problems.append(f"initial states differ: spec {len(ti)}, reference {len(ri)}")
    if ts != rs: problems.append(f"reachable states differ: only in spec {len(ts - rs)} e.g. {sorted(ts - rs, key=str)[:2]}; only in reference {len(rs - ts)} e.g. {sorted(rs - ts, key=str)[:2]}")
    if te != re_: problems.append(f"transitions differ: only in spec {len(te - re_)} e.g. {sorted(te - re_, key=str)[:2]}; only in reference {len(re_ - te)} e.g. {sorted(re_ - te, key=str)[:2]}")
    print(json.dumps({"states": len(ts), "initial": len(ti), "transitions": len(te), "problems": problems}))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
