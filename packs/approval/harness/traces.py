"""
harness/traces.py — run the reviewed traces of model/traces.yaml against the reference model. FROZEN.

    python3 harness/traces.py              exit 0 iff every step and every end state is as written
    python3 harness/traces.py --markdown   the traces as a table, for the author's review before sealing

The traces are the formalization-review artifact: a reader checks each one against INTENT.md by hand, and each
known-wrong design behaves differently on at least one (named in the file). They run against harness/reference.py,
which harness/refines.py shows equal to model/Approval.tla within the bounds the traces stay inside.
"""
import json, pathlib, re, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import reference as R

ROLES = {"alice": ("editor", "approver"), "bob": ("editor", "approver"), "carol": ("approver",), "dave": ("publisher",), "erin": ("approver",)}   # model/MC.tla
STEP = re.compile(r"^(\w+) (create|edit|submit|approve|reject|publish)(?: (\d+))?(?: quorum (\d+))? => (\w+)$")   # "alice create quorum 3 => OK"


def run(t):
    d = None; problems = []
    for i, s in enumerate(t["steps"], 1):
        m = STEP.match(s)
        if not m or (m[4] and m[2] != "create"): problems.append(f"step {i} unreadable: {s!r}"); break
        actor, op, rev, want = m[1], m[2], int(m[3]) if m[3] else None, m[5]
        if op == "create":
            why, nd = R.create(actor, ROLES, int(m[4]) if m[4] else R.DEFAULT_QUORUM)
            if d is None and nd is not None: d = nd
        else:
            why, d = R.step(d, op, actor, ROLES, rev)
        got = why or "OK"
        if got != want: problems.append(f"step {i} {s!r}: the reference gives {got}")
    v = R.view(d) if d else {}
    for k, want in t["end"].items():
        if v.get(k) != want: problems.append(f"end {k}: the reference gives {v.get(k)!r}, the trace says {want!r}")
    return problems


def main():
    T = yaml.safe_load((ROOT / "model/traces.yaml").read_text())
    if sys.argv[1:] == ["--markdown"]:
        print("| Trace | Says | Steps | End |\n|---|---|---|---|")
        for t in T:
            print(f"| {t['id']} | {t['says']} | {'<br>'.join(t['steps'])} | {', '.join(f'{k} {v}' for k, v in t['end'].items())} |")
        return 0
    bad = {t["id"]: p for t in T if (p := run(t))}
    print(json.dumps({"traces": len(T), "accepting": sum(all(s.endswith("=> OK") for s in t["steps"]) for t in T), "problems": bad}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
