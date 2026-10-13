"""
delivery/delivery_adapter.py — pith.booking's delivery adapter. FROZEN.

Called by the evaluator (kind `adapter`): run(ctx) -> {status: passed | failed | incomplete, problems, claim, detail,
reviewer_context, release_conditions, failing, failure_category} (the last two since v0.9.0: an unavailable browser is a
missing tool, not a failure of the page). Delivery here means a page in a real browser (browser_workflows.py) that
completes BW1–BW6 and keeps BI1–BI3 under injected faults; the release condition on browser containment is the
evaluator's (gate/browser.py contained).
"""
import pathlib, sys
import yaml


def run(ctx):
    root = pathlib.Path(ctx.root); sys.path.insert(0, str(root))
    D = yaml.safe_load((root / "delivery/delivery.yaml").read_text())
    from gate import browser as GB
    from delivery import browser_workflows as bw
    try: b = bw.run(pathlib.Path(ctx.out) / "browser")
    except Exception as e: b = {"status": "failed", "detail": f"{type(e).__name__}: {e}"}
    problems = []
    results = {}
    for r in b.get("runs", []):
        for s in r["steps"]:
            x = results.setdefault(s["workflow"], {"ok": True, "evidence": []}); x["ok"] &= s["ok"]; x["evidence"].append(f"{r['viewport']}: {s['evidence']}")
    for i in b.get("interactions", []):
        x = results.setdefault(i["obligation"], {"ok": True, "evidence": []}); x["ok"] &= i["ok"]; x["evidence"].append(i["evidence"])
    if b["status"] == "unavailable": problems.append("browser unavailable: " + b.get("detail", "") + " (a blocker, not a pass; see SEED_CHROMIUM)")
    for w in D["required_workflows"] + D["required_interactions"]:
        if b["status"] != "unavailable" and not results.get(w["id"], {}).get("ok"):
            problems.append(f"{w['id']} ({w['name']}) not demonstrated: {(results.get(w['id']) or {'evidence': ['not run']})['evidence'][0][:200]}")
    status = "passed" if not problems else ("incomplete" if b["status"] == "unavailable" else "failed")
    contained = GB.contained(b.get("browser_sandbox"), ctx.isolation_enforced, b.get("browser_user"))
    return {"status": status, "problems": problems,
            "claim": f"real-browser workflows {[w['id'] for w in D['required_workflows']]} at {[r['viewport'] for r in b.get('runs', [])]}; "
                     f"interaction obligations {[i['id'] for i in D['required_interactions']]} under injected request faults "
                     f"(sandboxed={b.get('browser_sandbox')}, browser user={b.get('browser_user')})",
            "detail": {"workflows": results, "browser": {k: b.get(k) for k in ("status", "browser_sandbox", "browser_user", "chromium_version", "detail")}, "problems": problems},
            "reviewer_context": {"required_evaluations": [e["id"] for e in D["required_evaluations"]]},
            "release_conditions": [("browser", contained, "Chromium sandbox, or a separate unprivileged browser user under the enforced isolation profile")],
            "failing": sorted(k for k, v in results.items() if not v["ok"]),
            "failure_category": None if not problems else ("toolchain_unavailable" if b["status"] == "unavailable" else "violation")}
