"""
obligations/app/browser_workflows.py — ring-3 delivery obligations, frozen. Drives the application in a real
browser (Playwright/Chromium) against the candidate's service running as a separate process, at desktop and
mobile widths, through the affordances in UI-CONTRACT.md. These are tests of the required workflows; not a proof
of UX, accessibility, or honest intent (E1–E3 remain human reviews).

Environment: SEED_CHROMIUM=<path> to use a specific binary; SEED_ALLOW_UNSANDBOXED_BROWSER=1 only for trusted
candidates (the report records browser_sandbox, and release-readiness requires it to be true).
Status: passed | failed | unavailable (browser could not start: a blocker, never a pass).
"""
import json, os, pathlib, shutil, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}

sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service
def _client():
    s = Service(ROOT).start(); return s.client, s.stop

def run(out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"kind": "real-browser-workflow-tests", "status": "running", "runs": [], "browser_sandbox": None,
              "scope": "W1-W6 at desktop and mobile widths through UI-CONTRACT.md affordances; not an accessibility or whole-UI proof"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.update(status="unavailable", detail="playwright not installed"); return report
    client, stop = _client(); base = client.base
    try:
        with sync_playwright() as p:
            exe = os.environ.get("SEED_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
            sandbox = os.environ.get("SEED_ALLOW_UNSANDBOXED_BROWSER") != "1"
            opts = {"headless": True, "chromium_sandbox": sandbox}
            if exe: opts["executable_path"] = exe
            try:
                browser = p.chromium.launch(**opts)
            except Exception as e:
                report.update(status="unavailable", detail="Chromium could not launch: " + str(e)[:300]); return report
            report.update(browser_sandbox=sandbox, chromium_version=browser.version)
            for name, (w, h) in VIEWPORTS.items():
                acct = 100 + len(report["runs"])
                page = browser.new_page(viewport={"width": w, "height": h}); steps = []
                def step(wid, ok, evidence): steps.append({"workflow": wid, "ok": bool(ok), "evidence": evidence})
                def text(tid): return page.locator(f'[data-testid="{tid}"]').first.inner_text(timeout=5000)
                def fill(tid, v): page.locator(f'[data-testid="{tid}"]').first.fill(str(v), timeout=5000)
                def click(tid): page.locator(f'[data-testid="{tid}"]').first.click(timeout=5000)
                try:
                    page.goto(base + "/", timeout=15000)
                    fill("acct-id", acct); fill("acct-limit", 100); click("btn-create"); page.wait_for_timeout(300)
                    step("W1", "100" in text("available"), f"available shows {text('available')!r}")
                    fill("req-id", 1); fill("req-amount", 60); click("btn-authorize"); page.wait_for_timeout(300)
                    d = page.locator('[data-testid="decision"]').first
                    step("W2", d.get_attribute("data-decision") == "AUTHORIZED" and "40" in text("available"), f"decision={d.get_attribute('data-decision')} available={text('available')!r}")
                    c_auth = d.evaluate("e => getComputedStyle(e).color + '|' + getComputedStyle(e).backgroundColor")
                    fill("req-id", 2); fill("req-amount", 60); click("btn-authorize"); page.wait_for_timeout(300)
                    c_decl = d.evaluate("e => getComputedStyle(e).color + '|' + getComputedStyle(e).backgroundColor")
                    step("W3", d.get_attribute("data-decision") == "DECLINED" and c_auth != c_decl, f"decision={d.get_attribute('data-decision')} styles differ={c_auth != c_decl}")
                    rows = page.locator('[data-testid="hold-row"]'); n_before = rows.count()
                    rows.first.locator('[data-testid="btn-release"]').first.click(timeout=5000); page.wait_for_timeout(300)
                    step("W4", "100" in text("available") and page.locator('[data-testid="hold-row"]').count() == n_before - 1, f"available={text('available')!r} holds {n_before}->{page.locator('[data-testid=\"hold-row\"]').count()}")
                    step("W5", "auth.decided" in text("events") and "reservation.released" in text("events"), "events panel lists decided/released")
                    fill("req-id", 3); fill("req-amount", 30); click("btn-authorize"); page.wait_for_timeout(300)
                    rows = page.locator('[data-testid="hold-row"][data-request-id="3"]')
                    rows.first.locator('[data-testid="btn-capture"]').first.click(timeout=5000); page.wait_for_timeout(300)
                    step("W6", "30" in text("posted") and "70" in text("available") and rows.count() == 0 and "capture.posted" in text("events"), f"posted={text('posted')!r} available={text('available')!r}")
                    # replay: resubmitting request 1 shows a replay, not a new decision
                    fill("req-id", 1); fill("req-amount", 60); click("btn-authorize"); page.wait_for_timeout(300)
                    step("R", d.get_attribute("data-decision") == "AUTHORIZED" and "replay" in d.inner_text().lower(), f"replay shown: {d.inner_text()!r}")
                except Exception as e:
                    steps.append({"workflow": "error", "ok": False, "evidence": str(e)[:300]})
                page.screenshot(path=str(out_dir / f"{name}.png")); page.close()
                report["runs"].append({"viewport": name, "size": [w, h], "steps": steps, "screenshot": f"{name}.png"})
            browser.close()
    finally:
        stop()
    ok = all(s["ok"] for r in report["runs"] for s in r["steps"]) and len(report["runs"]) == len(VIEWPORTS)
    report["status"] = "passed" if ok else "failed"
    (out_dir / "browser-report.json").write_text(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    r = run(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "browser-evidence")); print(r["status"]); sys.exit(0 if r["status"] == "passed" else 1)
