"""
gate/browser.py — how a pack's delivery adapter launches a contained browser. FROZEN. Domain-free.

Containment is the evaluator's business, not a pack's: either Chromium's own sandbox, or (inside the supported
isolation profile, gate/isolation/) a launcher that runs the browser as a separate unprivileged user. A pack's
adapter calls launch_options() and reports browser_user() and the sandbox flag it got, and makes its own
release condition from them (docs/rfc/0002-generality.md). Environment:
  SEED_BROWSER_LAUNCHER   set by the isolation profile (gate/isolation/browser_as.py)
  SEED_CHROMIUM           a specific Chromium binary
  SEED_ALLOW_UNSANDBOXED_BROWSER=1   only for trusted candidates; recorded (sandbox=False)
Added in v0.8.0 (M3); the root pack's adapter keeps its own copy of the same logic.
"""
import os, shutil


def launch_options():
    """(Playwright chromium.launch kwargs, sandboxed?)"""
    exe = os.environ.get("SEED_BROWSER_LAUNCHER") or os.environ.get("SEED_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
    sandbox = os.environ.get("SEED_ALLOW_UNSANDBOXED_BROWSER") != "1"
    opts = {"headless": True, "chromium_sandbox": sandbox}
    if exe: opts["executable_path"] = exe
    return opts, sandbox


def browser_user():
    """Who the page's JavaScript runs as: 'uid N' under the isolation profile's launcher, else the judge's own user."""
    return ("uid " + os.environ["SEED_BROWSER_UID"]) if os.environ.get("SEED_BROWSER_LAUNCHER") and os.environ.get("SEED_BROWSER_UID") else "judge"


def contained(sandboxed, isolation_enforced, user):
    """The release condition a browser-delivering pack should add: Chromium's sandbox, or a separate unprivileged
    browser user inside an enforced isolation profile."""
    return bool(sandboxed) or (bool(isolation_enforced) and user not in (None, "judge"))
