"""
obligations/app/delivery_adapter.py — the reservation pack's delivery adapter. FROZEN.

The evaluator (gate/kinds.py, kind `adapter`) calls run(ctx) and knows nothing of what is below. This is where the
pack decides what "an application was delivered" means for this domain: the structural SPEC lint (lint.py), the
real-browser workflows W1–W6 and interaction obligations I1–I6 (browser_workflows.py), and the required ids in
delivery.yaml. Another pack could deliver a CLI, a library or a mobile app through an adapter of its own; a browser
is not a universal requirement.

run(ctx) returns {status: passed | failed | incomplete, problems: [...], claim, detail (claims.delivery_detail),
reviewer_context, reviewer_flags, release_conditions: [(name, ok, requirement)], failing: [obligation ids],
failure_category} (the last two since v0.9.0: an incomplete SPEC is missing evidence, an unavailable browser is a missing
tool, a probe that never reached its precondition did not exercise the obligation, anything else is a violation).
"""
import json, pathlib, subprocess, sys
import yaml


def run(ctx):
    root = pathlib.Path(ctx.root)
    D = yaml.safe_load((root / "obligations/app/delivery.yaml").read_text())
    r = subprocess.run(f"{ctx.python} obligations/app/lint.py", cwd=root, shell=True, capture_output=True, text=True); o = r.stdout + r.stderr
    dl_fail = []; lint = {"evaluations": {}, "flags": []}
    if r.returncode != 0: dl_fail.append(o.strip())
    else:
        try: lint = json.loads(o.strip().splitlines()[-1])
        except Exception: dl_fail.append("lint produced no summary")
    browser = {"status": "unavailable", "detail": "lint failed; browser not run"}
    if not dl_fail:
        sys.path.insert(0, str(root / "obligations" / "app")); sys.path.insert(0, str(root))
        import browser_workflows as bw; bw.ROOT = root
        try: browser = bw.run(pathlib.Path(ctx.out) / "browser")
        except Exception as e: browser = {"status": "failed", "detail": f"{type(e).__name__}: {e}"}
    if browser["status"] == "unavailable": dl_fail.append("browser workflows unavailable: " + browser.get("detail", "") + " (a blocker, not a pass; see SEED_CHROMIUM)")
    elif browser["status"] != "passed":
        failed = [(r_["viewport"], s_["workflow"], s_["evidence"][:80]) for r_ in browser.get("runs", []) for s_ in r_["steps"] if not s_["ok"]]
        dl_fail.append(f"browser workflows failed: {failed[:4] or browser.get('detail')}")
    results = {}
    for r_ in browser.get("runs", []):
        for s_ in r_["steps"]:
            results.setdefault(s_["workflow"], {"ok": True, "evidence": []}); results[s_["workflow"]]["ok"] &= s_["ok"]; results[s_["workflow"]]["evidence"].append(f"{r_['viewport']}: {s_['evidence']}")
    for i in browser.get("interactions", []):
        results.setdefault(i["obligation"], {"ok": True, "evidence": []}); results[i["obligation"]]["ok"] &= i["ok"]; results[i["obligation"]]["evidence"].append(i["evidence"])
    if browser["status"] == "failed":
        dl_fail.extend(f"interaction {i['obligation']} failed: {i['evidence'][:160]}" for i in browser.get("interactions", []) if not i["ok"])
    for w in D["required_workflows"] + D.get("required_interactions", []):
        res = results.get(w["id"])
        if browser["status"] == "passed" and not (res and res.get("ok")): dl_fail.append(f"{w['id']} not demonstrated in the browser")
    status = "passed" if not dl_fail else ("failed" if browser["status"] == "failed" else "incomplete")
    failing = sorted(k for k, v in results.items() if not v["ok"])
    category = (None if not dl_fail else "evidence_missing" if r.returncode != 0 else "toolchain_unavailable" if browser["status"] == "unavailable"
                else "not_exercised" if failing and all(all("precondition not reached" in e for e in results[k]["evidence"] if e) for k in failing) else "violation")
    sandboxed = browser.get("browser_sandbox") is True
    contained = sandboxed or (ctx.isolation_enforced and browser.get("browser_user") not in (None, "judge"))   # Chromium's sandbox, or a separate unprivileged user inside the enforced profile
    return {"status": status, "problems": dl_fail,
            "claim": f"real-browser workflows {[w['id'] for w in D['required_workflows']]} + replay display passed at {[r_['viewport'] for r_ in browser.get('runs', [])]}; "
                     f"interaction obligations {[i['id'] for i in D.get('required_interactions', [])]} passed under injected response faults "
                     f"(sandboxed={browser.get('browser_sandbox')}, browser user={browser.get('browser_user')}); SPEC structurally complete (lint is structural, not semantic)",
            "detail": {"workflows": results, "browser": {k_: browser.get(k_) for k_ in ("status", "browser_sandbox", "browser_user", "chromium_version", "detail")}, "problems": dl_fail},
            "reviewer_context": {"spec_table_informational": lint.get("evaluations", {}), "semantic_flags_for_reviewers": lint.get("flags", [])},
            "reviewer_flags": lint.get("flags", []),
            "release_conditions": [("browser", contained, "Chromium sandbox, or a separate unprivileged browser user under the enforced isolation profile")],
            "failing": failing, "failure_category": category}
