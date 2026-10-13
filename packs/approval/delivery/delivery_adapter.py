"""
delivery/delivery_adapter.py — pith.approval's delivery adapter. FROZEN.

Called by the evaluator (kind `adapter`): run(ctx) -> {status: passed | failed, problems, claim, detail, failing,
failure_category} (the last two since v0.9.0: the workflows raising inside the judge is the evaluator's failure). Delivery here
means the candidate's command-line client (cli_workflows.py) completes AW1–AW5 and keeps AI1–AI3 under injected
faults. No browser is involved, so this pack adds no release condition; it asks for no human evaluation.
"""
import pathlib, sys
import yaml


def run(ctx):
    root = pathlib.Path(ctx.root); sys.path.insert(0, str(root))
    D = yaml.safe_load((root / "delivery/delivery.yaml").read_text())
    from delivery import cli_workflows as cw
    crashed = False
    try: b = cw.run(pathlib.Path(ctx.out) / "cli")
    except Exception as e: b = {"status": "failed", "results": [], "detail": f"{type(e).__name__}: {e}"}; crashed = True
    results = {}
    for r in b.get("results", []):
        x = results.setdefault(r["obligation"], {"ok": True, "evidence": []}); x["ok"] &= r["ok"]; x["evidence"].append(r["evidence"])
    problems = [f"{w['id']} ({w['name']}) not demonstrated: {(results.get(w['id']) or {'evidence': [b.get('detail') or 'not run']})['evidence'][0][:300]}"
                for w in D["required_workflows"] + D["required_interactions"] if not results.get(w["id"], {}).get("ok")]
    return {"status": "passed" if not problems else "failed", "problems": problems,
            "claim": f"CLI workflows {[w['id'] for w in D['required_workflows']]} and interaction obligations "
                     f"{[i['id'] for i in D['required_interactions']]} under a judge-owned fault proxy and an unreachable address "
                     f"({b.get('runs', 0)} CLI runs as the candidate's user)",
            "detail": {"workflows": results, "problems": problems},
            "failing": sorted(k for k, v in results.items() if not v["ok"]),
            "failure_category": None if not problems else ("infrastructure" if crashed else "violation")}
