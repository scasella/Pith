"""
obligations/app/browser_workflows.py — ring-3 delivery obligations, frozen. Drives the application in a real
browser (Playwright/Chromium) against the candidate's service running as a separate process, through the
affordances in UI-CONTRACT.md. Two parts:

  * workflows W1–W6 + replay, at desktop and mobile widths (the required workflows of delivery.yaml);
  * interaction obligations I1–I6 (delivery.yaml:required_interactions), at desktop width, with judge-programmed
    response faults: delayed, lost and failed responses, and several accounts sharing request ids. They check the
    mapping from what the page shows and what the user selects to the operation the page submits — the gap the
    Club Desk / Office Desk review found, which the core's proofs do not reach.

The page under test is unmodified: the browser loads it through a judge-owned proxy (faultproxy.py) that forwards
to the real service and applies the faults; every judgement is made from the service's own state (read through the
frozen client) and from DOM attributes the contract names. These are tests, not a proof of UX, accessibility, or
honest intent (E1–E3 remain human reviews).

Environment: SEED_CHROMIUM=<path> to use a specific binary; SEED_ALLOW_UNSANDBOXED_BROWSER=1 only for trusted
candidates (the report records browser_sandbox, and release-readiness requires it to be true, or the browser to run
as a separate unprivileged user inside an enforced isolation profile: see obligations/isolation/).
Status: passed | failed | unavailable (browser could not start: a blocker, never a pass).
"""
import json, os, pathlib, shutil, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}
SETTLE = 400            # ms to let the page react after an action
NO_RECEIPT = (None, "", "NONE")

sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service
from obligations.app.faultproxy import FaultProxy


def _launch_opts():
    exe = os.environ.get("SEED_BROWSER_LAUNCHER") or os.environ.get("SEED_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
    sandbox = os.environ.get("SEED_ALLOW_UNSANDBOXED_BROWSER") != "1"
    opts = {"headless": True, "chromium_sandbox": sandbox}
    if exe: opts["executable_path"] = exe
    return opts, sandbox


class Page:
    """Contract-level access to one page: affordances by data-testid, never by the application's own ids."""
    def __init__(self, page): self.p = page
    def loc(self, tid): return self.p.locator(f'[data-testid="{tid}"]')
    def text(self, tid): return self.loc(tid).first.inner_text(timeout=5000)
    def attr(self, tid, name):
        l = self.loc(tid)
        return l.first.get_attribute(name, timeout=2000) if l.count() else None
    def fill(self, tid, v):
        try: self.loc(tid).first.fill(str(v), timeout=2000); return True
        except Exception: return False                  # a disabled input is a legitimate choice; the effect is judged
    def click(self, tid, scope=None, timeout=5000):
        l = (scope or self.p).locator(f'[data-testid="{tid}"]').first
        try: l.click(timeout=timeout); return True
        except Exception: return False                  # a disabled or absent action is judged by its effect, not here
    def wait(self, ms=SETTLE): self.p.wait_for_timeout(ms)
    def rows(self):
        return [{"request_id": r.get_attribute("data-request-id"), "account_id": r.get_attribute("data-account-id")}
                for r in self.loc("hold-row").all()]
    def view(self):
        return {"loaded_account": self.attr("loaded-account", "data-account-id"), "view_state": self.attr("loaded-account", "data-state"),
                "available": self.text("available") if self.loc("available").count() else None, "holds": self.rows(),
                "decision": self.attr("decision", "data-decision"), "decision_account": self.attr("decision", "data-account-id"),
                "decision_request": self.attr("decision", "data-request-id")}
    def load(self, acct):
        self.fill("acct-id", acct); self.click("btn-load"); self.wait()


def _num(s):
    import re
    m = re.findall(r"-?\d+", s or ""); return int(m[0]) if m else None


def _precondition(pg, acct):
    """Non-vacuity: the probe only means something once the page shows the account's hold through the contract."""
    v = pg.view()
    if v["loaded_account"] != str(acct) or not any(r["request_id"] == "1" for r in v["holds"]):
        return f"precondition not reached: after loading account {acct} the page must declare it in loaded-account and show its hold (request 1) as a hold-row; saw {v}"
    return None


def _consistent(v, client):
    """The displayed holds and available figure belong to the account the page says is loaded."""
    if not v["loaded_account"]: return not v["holds"], "no loaded account declared" + ("" if not v["holds"] else " but holds are displayed")
    try: aid = int(v["loaded_account"])
    except ValueError: return False, f"loaded-account carries {v['loaded_account']!r}, not an account id"
    code, acct = client.account(aid)
    if code != 200: return False, f"page says account {aid} is loaded; the service has no such account"
    shown = sorted(r["request_id"] for r in v["holds"]); actual = sorted(acct["holds"].keys())
    wrong_rows = [r for r in v["holds"] if r["account_id"] != str(aid)]
    ok = shown == actual and _num(v["available"]) == acct["available"] and not wrong_rows
    return ok, f"loaded={aid} shown holds={shown} actual={actual} shown available={v['available']!r} actual={acct['available']} rows bound elsewhere={wrong_rows}"


def interactions(browser, client, proxy, base, ids):
    """I1–I6. Each probe uses fresh accounts that share request id 1, so a request id alone never identifies a hold."""
    out = []
    def probe(iid, fn):
        page = browser.new_page(viewport={"width": 1280, "height": 800}); proxy.clear(); n0 = len(proxy.log)
        try:
            page.goto(base + "/", timeout=15000); ok, evidence = fn(Page(page))
        except Exception as e:
            ok, evidence = False, f"{type(e).__name__}: {str(e)[:300]}"
        proxy.clear()
        out.append({"obligation": iid, "ok": bool(ok), "evidence": evidence,
                    "requests": [{k: r[k] for k in ("method", "path", "body", "status", "upstream_status")} | {"fault": bool(r["fault"])} for r in proxy.log[n0:]]})
        page.close()

    def pair(holds_a, holds_b):
        a, b = next(ids), next(ids)
        for acct, holds in ((a, holds_a), (b, holds_b)):
            client.create(acct, 100)
            for rid, amt in holds: client.authorize(acct, rid, amt)
        return a, b

    def snapshot(*accts): return {x: client.account(x)[1] for x in accts}
    def posts_to(acct): return [r for r in proxy.log if r["method"] == "POST" and r["path"].startswith(f"/accounts/{acct}/")]

    # I1 action-target binding: a displayed hold's action targets that hold's account, not the editable account field.
    for action in ("release", "capture"):
        def i1(pg, action=action):
            a, b = pair([(1, 20)], [(1, 30)]); before = snapshot(a, b)
            pg.load(a); pre = _precondition(pg, a)
            if pre: return False, pre
            pg.fill("acct-id", b)                                    # draft edit, not loaded
            row = pg.p.locator('[data-testid="hold-row"][data-request-id="1"]').first
            if row.count(): pg.click(f"btn-{action}", scope=row); pg.wait()
            after = snapshot(a, b)
            ok = after[b] == before[b] and not posts_to(b)
            return ok, f"account {a} loaded, account field edited to {b}, {action} clicked on the displayed hold: account {b} {'unchanged' if after[b] == before[b] else 'CHANGED ' + json.dumps(after[b])}; account {a} {json.dumps(after[a])}; mutations sent to {b}: {len(posts_to(b))}"
        probe("I1", i1)

    # I2 failed switch: when loading another account fails, the displayed holds still act on (and only on) their own account.
    for action in ("release", "capture"):
        def i2(pg, action=action):
            a, b = pair([(1, 20)], [(1, 30)]); before = snapshot(a, b)
            pg.load(a); pre = _precondition(pg, a)
            if pre: return False, pre
            proxy.fault("GET", f"/accounts/{b}", status=503, times=1, message="judge-injected transient load failure")
            pg.load(b); v = pg.view()
            row = pg.p.locator('[data-testid="hold-row"][data-request-id="1"]').first
            if row.count(): pg.click(f"btn-{action}", scope=row); pg.wait()
            after = snapshot(a, b); cons, why = _consistent(pg.view(), client)
            ok = after[b] == before[b] and not posts_to(b) and cons
            return ok, f"load of {b} failed once (503); then {action} on the displayed hold: account {b} {'unchanged' if after[b] == before[b] else 'CHANGED ' + json.dumps(after[b])}; view after: {why}; view during: {v}"
        probe("I2", i2)

    # I3 view consistency: a late response for a superseded selection never overwrites the newer one.
    def i3(pg):
        a, b = pair([(1, 20)], [(1, 30), (2, 10)])
        proxy.fault("GET", f"/accounts/{a}", delay=1.5, times=1, message="judge-delayed response")
        pg.fill("acct-id", a); pg.click("btn-load", timeout=1000)
        pg.wait(150); pg.fill("acct-id", b); pg.click("btn-load", timeout=1000)
        pg.wait(2600); v = pg.view(); cons, why = _consistent(v, client)
        asked_b = any(r["method"] == "GET" and r["path"] == f"/accounts/{b}" for r in proxy.requests())
        newest = str(b) if asked_b else str(a)                       # a page that blocked the second load keeps the first
        return cons and v["loaded_account"] == newest, f"newest selection the page requested: {newest}; load {a} (response delayed 1.5 s), then load {b}: {why}"
    probe("I3", i3)

    # I4 receipt preservation: a received decision survives a failed refresh, and the stale view is marked as stale.
    def i4(pg):
        c = next(ids); client.create(c, 100); pg.load(c)
        proxy.fault("GET", f"/accounts/{c}", status=503, message="judge-injected refresh failure after commit")
        pg.fill("req-id", 1); pg.fill("req-amount", 60); pg.click("btn-authorize"); pg.wait(700)
        v = pg.view(); actual = client.account(c)[1]
        kept = v["decision"] == "AUTHORIZED" and v["decision_request"] == "1" and v["decision_account"] == str(c)
        honest = v["view_state"] == "stale" or (_num(v["available"]) == actual["available"] and v["view_state"] == "current")
        proxy.clear(); pg.load(c); v2 = pg.view(); cons, why = _consistent(v2, client)
        recovered = cons and v2["view_state"] == "current"
        return kept and honest and recovered, f"authorize 60 succeeded (service: available {actual['available']}), refresh failed: decision={v['decision']} request={v['decision_request']} account={v['decision_account']} view_state={v['view_state']} available shown={v['available']!r}; after reload: {why} view_state={v2['view_state']}"
    probe("I4", i4)

    # I5 outcome/view separation: lost response = UNKNOWN; service refusal = REJECTED; a same-id retry shows the receipt.
    def i5(pg):
        d = next(ids); client.create(d, 100); pg.load(d)
        proxy.fault("POST", f"/accounts/{d}/authorize", status=503, forward=True, times=1, message="judge-injected lost response (the service committed)")
        pg.fill("req-id", 1); pg.fill("req-amount", 10); pg.click("btn-authorize"); pg.wait(700); lost = pg.view()
        pg.fill("req-id", 1); pg.fill("req-amount", 20); pg.click("btn-authorize"); pg.wait(); conflict = pg.view()
        pg.fill("req-id", 1); pg.fill("req-amount", 10); pg.click("btn-authorize"); pg.wait(); retry = pg.view()
        ok = (lost["decision"] == "UNKNOWN" and conflict["decision"] == "REJECTED" and retry["decision"] == "AUTHORIZED"
              and retry["decision_request"] == "1" and retry["decision_account"] == str(d))
        return ok, f"lost response -> {lost['decision']} (want UNKNOWN); conflicting reuse -> {conflict['decision']} (want REJECTED); same-id retry -> {retry['decision']} for request {retry['decision_request']} account {retry['decision_account']} (want AUTHORIZED, 1, {d})"
    probe("I5", i5)

    # I6 receipt scope: after switching account, a shown receipt still names the account it came from (or is cleared).
    def i6(pg):
        e, f = pair([], [])
        pg.load(e); pg.fill("req-id", 1); pg.fill("req-amount", 10); pg.click("btn-authorize"); pg.wait()
        pg.load(f); v = pg.view(); cons, why = _consistent(v, client)
        scoped = v["decision"] in NO_RECEIPT or v["decision_account"] == str(e)
        return scoped and cons and v["loaded_account"] == str(f), f"receipt on {e}, then load {f}: decision={v['decision']} decision account={v['decision_account']} (cleared or {e}); {why}"
    probe("I6", i6)
    return out


def run(out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"kind": "real-browser-workflow-tests", "status": "running", "runs": [], "interactions": [], "browser_sandbox": None,
              "browser_user": ("uid " + os.environ["SEED_BROWSER_UID"]) if os.environ.get("SEED_BROWSER_LAUNCHER") and os.environ.get("SEED_BROWSER_UID") else "judge",
              "scope": "W1-W6 + replay at desktop and mobile widths; interaction obligations I1-I6 at desktop width with judge-injected response faults; through UI-CONTRACT.md affordances; not an accessibility or whole-UI proof"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.update(status="unavailable", detail="playwright not installed"); return report
    svc = Service(ROOT).start(); client = svc.client; proxy = FaultProxy(client.base).start(); base = proxy.base
    try:
        with sync_playwright() as p:
            opts, sandbox = _launch_opts()
            try:
                browser = p.chromium.launch(**opts)
            except Exception as e:
                report.update(status="unavailable", detail="Chromium could not launch: " + str(e)[:300]); return report
            report.update(browser_sandbox=sandbox, chromium_version=browser.version)
            for name, (w, h) in VIEWPORTS.items():
                acct = 100 + len(report["runs"])
                page = browser.new_page(viewport={"width": w, "height": h}); steps = []; pg = Page(page)
                def step(wid, ok, evidence): steps.append({"workflow": wid, "ok": bool(ok), "evidence": evidence})
                text, fill, click = pg.text, pg.fill, pg.click
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
            ids = iter(range(500, 10_000))
            report["interactions"] = interactions(browser, client, proxy, base, ids)
            browser.close()
    finally:
        proxy.stop(); svc.stop()
    (out_dir / "interaction-requests.json").write_text(json.dumps(report["interactions"], indent=2))
    ok = (all(s["ok"] for r in report["runs"] for s in r["steps"]) and len(report["runs"]) == len(VIEWPORTS)
          and report["interactions"] and all(i["ok"] for i in report["interactions"]))
    report["status"] = "passed" if ok else "failed"
    for i in report["interactions"]: i.pop("requests", None)        # full request logs are in interaction-requests.json
    (out_dir / "browser-report.json").write_text(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    r = run(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "browser-evidence")); print(r["status"]); sys.exit(0 if r["status"] == "passed" else 1)
