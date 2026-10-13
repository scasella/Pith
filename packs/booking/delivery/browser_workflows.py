"""
delivery/browser_workflows.py — application delivery for pith.booking, in a real browser. FROZEN.

Drives the candidate's page (Playwright/Chromium), served by the candidate's service running as a separate process,
through the affordances of UI-CONTRACT.md: workflows BW1–BW6 at desktop and mobile widths, and interaction
obligations BI1–BI3 at desktop width with request faults injected by the judge (Playwright request interception:
the page under test is unmodified). Every outcome is judged from the service's own state, read with the frozen
client, and from the attributes the contract names. Browser containment comes from the evaluator (gate/browser.py).
Status: passed | failed | unavailable (no browser: a blocker, never a pass).
"""
import json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate import browser as GB
from harness.supervisor import Service

VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}
RECEIPT_ATTRS = ("data-outcome", "data-booking-id", "data-resource-id", "data-conflicts-with")


def hhmm(m): return f"{m // 60:02d}:{m % 60:02d}"


class Page:
    def __init__(self, page): self.p = page
    def loc(self, tid, scope=None): return (scope or self.p).locator(f'[data-testid="{tid}"]')
    def fill(self, tid, v, scope=None):
        try: self.loc(tid, scope).first.fill(str(v), timeout=3000); return True
        except Exception: return False
    def click(self, tid, scope=None):
        try: self.loc(tid, scope).first.click(timeout=4000); return True
        except Exception: return False
    def receipt(self):
        l = self.loc("receipt")
        if not l.count(): return {}
        return {a: l.first.get_attribute(a) for a in RECEIPT_ATTRS}
    def act(self, fn, timeout=4.0):
        """Do fn() and wait until the receipt changes; returns the new receipt (or the old one if nothing changed)."""
        before = self.receipt(); fn(); t0 = time.time()
        while time.time() - t0 < timeout:
            self.p.wait_for_timeout(100); now = self.receipt()
            if now != before and now.get("data-outcome"): self.p.wait_for_timeout(250); return self.receipt()
        return self.receipt()
    def row(self, bid): return self.p.locator(f'[data-testid="booking-row"][data-booking-id="{bid}"]').first
    def row_attr(self, bid, a):
        r = self.p.locator(f'[data-testid="booking-row"][data-booking-id="{bid}"]')
        return r.first.get_attribute(a) if r.count() else None
    def style(self): return self.loc("receipt").first.evaluate("e => getComputedStyle(e).color + '|' + getComputedStyle(e).backgroundColor + '|' + getComputedStyle(e).borderColor")
    def book(self, s, e):
        self.fill("book-start", hhmm(s)); self.fill("book-end", hhmm(e)); return self.act(lambda: self.click("book-submit"))
    def move(self, bid, s, e):
        r = self.row(bid); self.fill("move-start", hhmm(s), r); self.fill("move-end", hhmm(e), r); return self.act(lambda: self.click("move-submit", r))
    def cancel(self, bid): r = self.row(bid); return self.act(lambda: self.click("cancel", r))
    def show(self, rid):
        self.fill("resource-pick", rid); self.click("resource-load"); self.p.wait_for_timeout(500)


def bid_of(rc):
    try: return int(rc.get("data-booking-id"))
    except (TypeError, ValueError): return None


def svc_slot(c, bid):
    code, b = c.booking(bid)
    return (b["start"], b["end"], b["active"]) if code == 200 else None


def workflows(page, c, rid):
    pg = Page(page); steps = []
    def step(wid, ok, ev): steps.append({"workflow": wid, "ok": bool(ok), "evidence": ev})
    pg.fill("resource-id", rid); pg.fill("resource-name", f"Room {rid}"); pg.click("resource-create"); page.wait_for_timeout(500)
    cal = pg.loc("calendar")
    step("BW1", c.resource(rid)[0] == 200 and cal.count() and cal.first.get_attribute("data-resource-id") == str(rid),
         f"service has resource {rid}: {c.resource(rid)[0] == 200}; calendar shows {cal.first.get_attribute('data-resource-id') if cal.count() else None}")
    r1 = pg.book(600, 660); b1 = bid_of(r1); s_acc = pg.style() if r1 else None
    step("BW2", r1.get("data-outcome") == "ACCEPTED" and b1 and svc_slot(c, b1) == (600, 660, True) and pg.row_attr(b1, "data-start") == "600",
         f"receipt {r1}; service {svc_slot(c, b1) if b1 else None}; row start {pg.row_attr(b1, 'data-start') if b1 else None}")
    r2 = pg.book(630, 690); n_active = len([b for b in c.resource(rid)[1]["bookings"] if b["active"]])
    step("BW3", r2.get("data-outcome") == "CONFLICT" and r2.get("data-conflicts-with") == str(b1) and n_active == 1 and pg.style() != s_acc,
         f"receipt {r2}; active bookings in the service {n_active}; style differs from ACCEPTED: {pg.style() != s_acc}")
    r3 = pg.book(660, 720); b2 = bid_of(r3)
    step("BW4", r3.get("data-outcome") == "ACCEPTED" and b2 and svc_slot(c, b2) == (660, 720, True) and svc_slot(c, b1) == (600, 660, True),
         f"[11:00, 12:00) after [10:00, 11:00): receipt {r3}; service {svc_slot(c, b2) if b2 else None}")
    m1 = pg.move(b2, 780, 840); ok1 = m1.get("data-outcome") == "ACCEPTED" and svc_slot(c, b2) == (780, 840, True) and pg.row_attr(b2, "data-start") == "780"
    m2 = pg.move(b1, 810, 870); ok2 = m2.get("data-outcome") == "CONFLICT" and svc_slot(c, b1) == (600, 660, True) and pg.row_attr(b1, "data-start") == "600"
    step("BW5", ok1 and ok2, f"free move: receipt {m1}, service {svc_slot(c, b2)}; taken move: receipt {m2}, service {svc_slot(c, b1)}, row start {pg.row_attr(b1, 'data-start')}")
    x = pg.cancel(b1); again = pg.book(600, 660); b3 = bid_of(again)
    step("BW6", x.get("data-outcome") == "CANCELLED" and svc_slot(c, b1) == (600, 660, False) and again.get("data-outcome") == "ACCEPTED" and b3 and svc_slot(c, b3) == (600, 660, True),
         f"cancel receipt {x}; service {svc_slot(c, b1)}; rebook receipt {again}")
    return steps


def interactions(browser, c, base, rids):
    out = []
    def probe(oid, fn):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(base + "/", timeout=15000); ok, ev = fn(page, Page(page), next(rids))
        except Exception as e:
            ok, ev = False, f"probe error: {type(e).__name__}: {str(e)[:200]}"
        page.close(); out.append({"obligation": oid, "ok": bool(ok), "evidence": ev})

    def bi1(page, pg, rid):                         # receipt preservation across a failed refresh
        c.create(rid, f"Room {rid}"); pg.show(rid)
        armed = {"on": False, "failed": 0}
        def h(route):
            if armed["on"] and route.request.method == "GET": armed["failed"] += 1; return route.fulfill(status=500, body='{"error":"injected"}', content_type="application/json")
            route.continue_()
        page.route(f"**/resources/{rid}", h); page.route(f"**/resources/{rid}?*", h)
        armed["on"] = True; r = pg.book(600, 660); page.wait_for_timeout(800); r = pg.receipt(); b = bid_of(r)
        reached = armed["failed"] > 0 and any(x["active"] for x in c.resource(rid)[1]["bookings"])
        return (reached and r.get("data-outcome") == "ACCEPTED" and b is not None and svc_slot(c, b) == (600, 660, True),
                f"refresh failures injected {armed['failed']}; receipt after them {r}; service {c.resource(rid)[1]['bookings']}")

    def bi2(page, pg, rid):                         # lost response after commit
        c.create(rid, f"Room {rid}"); pg.show(rid)
        seen = {"committed": 0}
        def h(route):
            if route.request.method == "POST": route.fetch(); seen["committed"] += 1; return route.abort("connectionreset")
            route.continue_()
        page.route(f"**/resources/{rid}/bookings", h)
        r = pg.book(600, 660)
        committed = [x for x in c.resource(rid)[1]["bookings"] if x["active"]]
        return (seen["committed"] == 1 and len(committed) == 1 and r.get("data-outcome") == "UNKNOWN",
                f"service committed {committed}; the page's receipt {r} (must be UNKNOWN)")

    def bi3(page, pg, rid):                         # row actions bind to the row's booking
        c.create(rid, f"Room {rid}"); base_id = 7_000_000_000 + rid * 10
        for k, (s, e) in enumerate(((540, 600), (600, 660), (660, 720))): c.book(rid, base_id + k, s, e)
        pg.show(rid); pg.fill("resource-pick", rid + 1000)          # edited but not loaded: must not matter
        a, b, d = base_id, base_id + 1, base_id + 2
        x = pg.cancel(b); m = pg.move(d, 900, 960)
        st = {i: svc_slot(c, i) for i in (a, b, d)}
        return (st == {a: (540, 600, True), b: (600, 660, False), d: (900, 960, True)} and x.get("data-booking-id") == str(b) and m.get("data-booking-id") == str(d),
                f"cancel on row {b} -> {x}; move on row {d} -> {m}; service {st}")

    for oid, fn in (("BI1", bi1), ("BI2", bi2), ("BI3", bi3)): probe(oid, fn)
    return out


def run(out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"kind": "real-browser-workflow-tests", "status": "running", "runs": [], "interactions": [], "browser_sandbox": None, "browser_user": GB.browser_user(),
              "scope": "BW1-BW6 at desktop and mobile widths; BI1-BI3 at desktop width with judge-injected request faults; through UI-CONTRACT.md affordances; not an accessibility or whole-UI proof"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.update(status="unavailable", detail="playwright not installed"); return report
    svc = Service(ROOT).start(); c = svc.client; base = svc.url()
    try:
        with sync_playwright() as p:
            opts, sandbox = GB.launch_options()
            try: browser = p.chromium.launch(**opts)
            except Exception as e:
                report.update(status="unavailable", detail="Chromium could not launch: " + str(e)[:300]); return report
            report.update(browser_sandbox=sandbox, chromium_version=browser.version)
            for n, (name, (w, h)) in enumerate(VIEWPORTS.items()):
                page = browser.new_page(viewport={"width": w, "height": h})
                try:
                    page.goto(base + "/", timeout=15000); steps = workflows(page, c, 100 + n)
                except Exception as e:
                    steps = [{"workflow": "error", "ok": False, "evidence": f"{type(e).__name__}: {str(e)[:300]}"}]
                page.screenshot(path=str(out_dir / f"{name}.png")); page.close()
                report["runs"].append({"viewport": name, "size": [w, h], "steps": steps, "screenshot": f"{name}.png"})
            report["interactions"] = interactions(browser, c, base, iter(range(500, 10_000)))
            browser.close()
    finally:
        svc.stop()
    ok = all(s["ok"] for r in report["runs"] for s in r["steps"]) and len(report["runs"]) == len(VIEWPORTS) and report["interactions"] and all(i["ok"] for i in report["interactions"])
    report["status"] = "passed" if ok else "failed"
    (out_dir / "browser-report.json").write_text(json.dumps(report, indent=2))
    return report
