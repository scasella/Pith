#!/usr/bin/env python3
"""
gate/isolation/browser_as.py — FROZEN. A launcher Playwright starts in place of Chromium
(SEED_BROWSER_LAUNCHER) when the judge runs as root inside the isolation profile. It hands the profile directory
Playwright created to SEED_BROWSER_UID, drops to that unprivileged user (no supplementary groups), and execs
SEED_CHROMIUM (default: the Playwright-managed Chromium under PLAYWRIGHT_BROWSERS_PATH) with the same arguments. Playwright's control pipe (fds 3 and 4) survives the exec, so the judge still
drives the browser, but the page — candidate JavaScript — runs as a user that cannot read the evidence directory or
the judge's files. Chromium's own sandbox is not available inside an unprivileged container; this is the containment
the report records instead (browser_sandbox=false, browser_user=<uid>).
"""
import os, sys

uid = int(os.environ["SEED_BROWSER_UID"]); gid = int(os.environ.get("SEED_BROWSER_GID") or uid)
args = sys.argv[1:]
for arg in args:
    if arg.startswith("--user-data-dir="):
        top = arg.split("=", 1)[1]
        for d, dirs, files in os.walk(top):
            os.chown(d, uid, gid)
            for f in files: os.chown(os.path.join(d, f), uid, gid)
home = f"/tmp/browser-home-{uid}"; os.makedirs(home, exist_ok=True); os.chown(home, uid, gid)
os.environ["HOME"] = home
os.setgroups([]); os.setgid(gid); os.setuid(uid)
if os.geteuid() == 0: sys.exit("browser_as: privilege drop failed")
exe = os.environ.get("SEED_CHROMIUM")
if not exe:                                        # the image's Playwright-managed Chromium
    import glob
    found = sorted(glob.glob(os.path.join(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw"), "chromium-*", "chrome-linux*", "chrome")))
    if not found: sys.exit("browser_as: no Chromium found; set SEED_CHROMIUM")
    exe = found[-1]
os.execv(exe, [exe] + args)
