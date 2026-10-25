#!/usr/bin/env python3
"""
obligations/boundary/render_trace.py — a harvested trace (pith.trace/v1) as a Dafny test against the verified core. FROZEN.

    python3 obligations/boundary/render_trace.py < trace.json > traces.dfy        (`traces.render` in pack.yaml; gate/trace.py harvest)

The rendering has the form of kernel/adequacy/traces.dfy: one `method {:test}` that runs the trace's steps through the verified
core (Core.Decide and Core.Release, Poster.Capture) on an Account value and `expect`s, after every step, what the contract
requires (the step's `expected`, which gate/trace.py took from the offline oracle): the decision, the availability the decision was
taken against, and the holds, the status of every request and the posted amount afterwards. `dafny test` runs it, so it shows what the
CORE does with these steps; whether a service does the same is the replay's question (obligations/boundary/replay.py).

Where it will be checked: `include "../core/Kernel.dfy"` is relative to a file one directory beside kernel/core (the way
kernel/adequacy/traces.dfy is); put the rendering under kernel/ (for example kernel/adequacy/) of a release, or copy kernel/ and place
it beside core/.

Availability: `Available` and `Sum` are ghost in AuthSpec, so a test cannot evaluate them. The rendering `expect`s the holds literally
(after every step) and then checks the step's expected `available_at_decision` as limit - posted - (the amounts of those holds), which
is the same quantity computed from values the test has just compared with the core's.

Steps whose expected answer is a refusal ({status: N}), a replay (replayed: true) or a no-op (released/captured: false) never reach the
core (the profile validates and answers from receipts before calling it), so they are carried as comments and change nothing.
"""
import json, re, sys


def lit(m): return "map[]" if not m else "map[" + ", ".join(f"{k} := {v}" for k, v in sorted(m.items())) + "]"
def sum_lit(holds): return " + ".join(str(v) for _, v in sorted(holds.items())) or "0"


def render(trace):
    steps = trace.get("steps", [])
    alert = re.sub(r"\W+", "_", str(trace.get("alert") or "divergence")).strip("_") or "divergence"
    out = [f"// traces.dfy — a regression trace harvested from a shadow divergence (gate/trace.py harvest; obligations/boundary/render_trace.py).",
           f"// Pack {trace.get('pack')}, contract records {trace.get('records')}, alert {trace.get('alert')}. Each `expect` is the answer the contract requires",
           "// (the offline oracle's); the last step is where a live service answered differently. `dafny test` runs it against the verified core:",
           "// `expect` failures are runtime failures, not proof failures. Unsigned: the provenance is traces.provenance.yaml.",
           'include "../core/Kernel.dfy"', "", "module HarvestedTrace {", "  import opened AuthSpec", "  import opened AuthCore", "  import opened PostingCore", "",
           f"  method {{:test}} Harvested_{alert}_{len(steps)}_steps() {{", "    var c := new Core(); var p := new Poster();"]
    acct = {}                                                                   # account id -> {limit, posted, holds {request: amount}, status {request: name}} as the contract requires it
    def comment(i, s, why): out.append(f"    // step {i}: {s['action']} {json.dumps(s.get('args', {}), sort_keys=True)} -> {json.dumps(s.get('expected'), sort_keys=True)}: {why}")
    for i, s in enumerate(steps, 1):
        a, args, exp = s["action"], s.get("args", {}), s.get("expected") or {}
        acc = args.get("account"); v = f"acct_{acc}"
        if "status" in exp: comment(i, s, "a refusal: the profile answers it before the core, no state change"); continue
        if a == "create_account":
            acct[acc] = {"limit": args["limit"], "posted": 0, "holds": {}, "status": {}}
            out += [f"    // step {i}: create_account {json.dumps(args, sort_keys=True)}", f"    var {v} := Account({args['limit']}, 0, map[], map[]);"]
            continue
        if acc not in acct: comment(i, s, "no such account in this trace"); continue
        st = acct[acc]; r = args.get("request")
        if exp.get("replayed"): comment(i, s, "a replay answered from its receipt: the core is not called"); continue
        if a == "authorize":
            decision = exp["decision"]; avail = exp["available_at_decision"]
            out += [f"    // step {i}: authorize {json.dumps(args, sort_keys=True)} -> {decision}, availability {avail}",
                    f"    expect {v}.holds == {lit(st['holds'])} && {v}.posted == {st['posted']};",
                    f"    expect {v}.limit as int - {v}.posted as int - ({sum_lit(st['holds'])}) == {avail};  // the availability this decision is taken against",
                    f"    expect {r} !in {v}.status;  // Decide's precondition: a new request",
                    f"    var d{i}: Decision; d{i}, {v} := c.Decide({v}, Request({r}, {args['amount']}));",
                    f"    expect d{i} == {'Authorized' if decision == 'AUTHORIZED' else 'Declined'};"]
            if decision == "AUTHORIZED": st["holds"][r] = args["amount"]; st["status"][r] = "Auth"
            else: st["status"][r] = "Decl"
        elif a == "release":
            if not exp.get("released"): comment(i, s, "nothing to release: the core is not called"); continue
            out += [f"    // step {i}: release {json.dumps(args, sort_keys=True)}", f"    expect {r} in {v}.holds;  // Release's precondition",
                    f"    {v} := c.Release({v}, {r});"]
            st["holds"].pop(r, None); st["status"][r] = "Rel"
        elif a == "capture":
            if not exp.get("captured"): comment(i, s, "nothing to capture: the core is not called"); continue
            out += [f"    // step {i}: capture {json.dumps(args, sort_keys=True)} -> posts {exp.get('amount')}", f"    expect {r} in {v}.holds && {v}.holds[{r}] == {exp.get('amount')};  // Capture's precondition, and the amount it posts",
                    f"    {v} := p.Capture({v}, {r});"]
            st["holds"].pop(r, None); st["posted"] += exp["amount"]; st["status"][r] = "Post"
        else: comment(i, s, "an action this rendering does not know"); continue
        out += [f"    expect {v}.holds == {lit(st['holds'])};", f"    expect {v}.posted == {st['posted']};",
                f"    expect {v}.status == {lit({k: x for k, x in st['status'].items()})};"]
    out += ["  }", "}", ""]
    return "\n".join(out)


def main():
    sys.stdout.write(render(json.load(sys.stdin)))


if __name__ == "__main__":
    main()
