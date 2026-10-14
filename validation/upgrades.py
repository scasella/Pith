#!/usr/bin/env python3
"""validation/upgrades.py OUT [PACK ...] — the contract upgrades of the main packs, judged the way M5 defines
(docs/rfc/0006-upgrading-the-main-packs.md; docs/rfc/0004-safe-evolution.md § 2, § 4, § 5).

validation/upgrades.yaml names, for each pack, the commit its previous release was published at, that release's
digest (as catalog.yaml recorded it), the applications to migrate and the known-wrong migrations. For each pack:

  1. the previous release, rebuilt from the commit, has exactly the recorded digest: the "old" side is the release
     that was published, not a reconstruction
  2. each old application (the same example at that commit) is accepted under the previous release, and the reference
     one is recorded for deployment (gate/deploy.py record)
  3. the upgrade is classified behavioral before anything is judged again (gate/change.py classify), naming the
     contract records that changed; the report says the old results hold for exactly the checks upgrades.yaml lists
     under `holds` (those whose inputs and contract records the upgrade did not reach; none when it reached them all)
  4. the reference application, judged under the new release with the old evidence offered (--reuse), is accepted and
     reuses nothing: evidence is bound to the release it was produced under (gate/evidence.py reusable), so even what
     the classification says still holds is checked again
  5. the old deployment record does not cover the new artifact (gate/deploy.py check)
  6. every application migrates state its own accepted old artifact produced (gate/migrate.py run --old-evidence):
     unrecognised state refused, migrate, migrate again, verify, rollback policy stated
  7. every known-wrong migration is refused at verify for exactly its defect, and the ones marked `judged` pass the
     ordinary judge: only the run with populated state catches them

Writes OUT/upgrades-record.json; exit 1 if any expectation fails. Needs the previous releases' commit in the local
history (CI fetches it); every judge runs the toolchain of its pack, so the reservation pack needs Dafny, TLC and a
browser."""
import json, os, pathlib, shutil, subprocess, sys, tarfile, io
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve()
CFG = yaml.safe_load((ROOT / "validation/upgrades.yaml").read_text())
only = sys.argv[2:]
rec = {"format": "pith.upgrades-record/v1", "from_commit": CFG["from_commit"], "packs": {}}; failures = []


def sh(*argv, cwd=ROOT, ok=(0,)):
    r = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True, text=True)
    if r.returncode not in ok: print(r.stdout[-3000:], r.stderr[-3000:]); raise SystemExit(f"FAILED ({r.returncode}): {' '.join(map(str, argv))}")
    return r


def expect(pack, what, cond, detail=""):
    rec["packs"].setdefault(pack, {"expectations": []})["expectations"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {pack}: {what}" + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond: failures.append(f"{pack}: {what}")


def old_tree():
    """The repository as it was at from_commit (git archive; fetched first if this clone does not have it)."""
    d = OUT / "old-src"
    if d.is_dir(): return d
    sha = CFG["from_commit"]
    if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True).returncode != 0:
        sh("git", "fetch", "--depth=1", "origin", sha)
    data = subprocess.run(["git", "archive", "--format=tar", sha], cwd=ROOT, capture_output=True, check=True).stdout
    d.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t: t.extractall(d, filter="data")
    return d


def release_id(rel): return sh(PY, rel / "gate/release.py", "id").stdout.strip()


def judge(rel, cand, out, reuse=None):
    r = subprocess.run([PY, "-I", rel / "gate/app_gate.py", "--candidate", cand, "--out", out, "--expected-release", release_id(rel)] + (["--reuse", reuse] if reuse else []),
                       cwd=ROOT, capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text()) if (out / "app-claims.json").exists() else {}
    E = json.loads((out / "evidence.json").read_text()) if (out / "evidence.json").exists() else {"records": []}
    if r.returncode != 0: print(r.stdout[-1500:], r.stderr[-1500:])
    return r.returncode, c, E


def reused(E): return sorted(r["check"] for r in E["records"] if r.get("reused_from"))


def overlay(base, extra, dest):
    """A candidate made of `base` with `extra`'s files on top (a known-wrong migration differs from its base in a few files)."""
    shutil.rmtree(dest, ignore_errors=True); shutil.copytree(base, dest)
    shutil.copytree(extra, dest, dirs_exist_ok=True)
    for f in ("expected.yaml",): (dest / f).unlink(missing_ok=True)
    return dest


def migrate(rel_new, cand, rel_old, old_cand, old_ev, out):
    """gate/migrate.py run, bound to the old evidence. --allow-not-ready: the old evidence of a pack whose acceptance
    includes a person's signed approval awaits it here (nobody in this repository can sign one); the report names it
    under from.awaiting_review, and nothing else may be unready."""
    r = subprocess.run([PY, "gate/migrate.py", "run", "--release", rel_new, "--candidate", cand, "--old-release", rel_old, "--old-candidate", old_cand,
                        "--old-evidence", old_ev, "--allow-not-ready", "--out", out], cwd=ROOT, capture_output=True, text=True)
    M = json.loads((out / "migration-report.json").read_text()) if (out / "migration-report.json").exists() else {"ok": False, "steps": []}
    if r.returncode != 0 and not M["steps"]: print(r.stdout[-1500:], r.stderr[-1500:])
    return r.returncode, M


def run_pack(name, S):
    W = OUT / name; W.mkdir(parents=True)
    src = old_tree(); pack_new = (ROOT / S["pack"]).resolve(); pack_old = (src / S["pack"]).resolve()
    rel_old, rel_new = W / "release-old", W / "release-new"
    sh(PY, src / "gate/release.py", "build", "--pack", pack_old, "--out", rel_old, cwd=src)
    sh(PY, "gate/release.py", "build", "--pack", pack_new, "--out", rel_new)
    ids = {"old": release_id(rel_old), "new": release_id(rel_new)}
    R = rec["packs"].setdefault(name, {"expectations": []}); R["releases"] = ids
    expect(name, "the previous release rebuilt from its commit has exactly the digest the catalog recorded", ids["old"] == S["old_release"], f"{ids['old']} vs {S['old_release']}")
    expect(name, "the new release is not the old one", ids["new"] != ids["old"])

    apps = S["applications"]; ref = apps[0]; ev_old = {}
    for app in apps:
        old = src / app.get("old", app["new"]); code, c, _ = judge(rel_old, old, W / f"ev-old-{pathlib.Path(app['new']).name}")
        ev_old[app["new"]] = W / f"ev-old-{pathlib.Path(app['new']).name}"
        expect(name, f"the old {app.get('old', app['new'])} is accepted under the previous release", code == 0, {k: c.get(k) for k in ("behavioral_assurance", "application_delivery")})
    first = ev_old[ref["new"]]; old_ref = src / ref.get("old", ref["new"])
    r = subprocess.run([PY, "gate/deploy.py", "record", "--evidence", first, "--release", rel_old, "--candidate", old_ref, "--out", W / "deploy-old.json", "--allow-not-ready"],
                       cwd=ROOT, capture_output=True, text=True)
    expect(name, "the old reference application is recorded for deployment", r.returncode == 0, r.stderr[-300:])

    cls = json.loads(sh(PY, "gate/change.py", "classify", "--evidence", first, "--candidate", ROOT / ref["new"], "--policy-from", rel_new, "--json").stdout)
    cc = {c["id"]: c["change"] for c in cls["contract_changes"]}
    want = S.get("contract_changes", {})
    expect(name, "the upgrade is classified behavioral, naming the changed contract records", cls["route"] == "behavioral" and all(cc.get(k) == v for k, v in want.items()), cc)
    holds = sorted(S.get("holds") or [])
    expect(name, f"the classification says the old results hold for exactly the {len(holds)} checks the upgrade did not reach", sorted(cls["evidence"]["holds"]) == holds, sorted(cls["evidence"]["holds"]))
    R["classify"] = {"route": cls["route"], "contract_changes": cls["contract_changes"], "ambiguous": cls["ambiguous"], "holds": cls["evidence"]["holds"], "rerun": cls["rerun"]}

    code, c, E = judge(rel_new, ROOT / ref["new"], W / "ev-new-reuse-old", reuse=first)
    expect(name, f"{ref['new']} judged under the new release with the old evidence offered: accepted, nothing reused", code == 0 and not reused(E), (code, reused(E)))
    r = subprocess.run([PY, "gate/deploy.py", "check", "--record", W / "deploy-old.json", "--release", rel_new, "--deployed", ROOT / ref["new"], "--json"], cwd=ROOT, capture_output=True, text=True)
    diff = {d["what"] for d in json.loads(r.stdout)["differences"]} if r.stdout.strip().startswith("{") else set()
    expect(name, "the old deployment record does not cover the new artifact", r.returncode == 1 and {"release", "artifact"} <= diff, sorted(diff))

    R["migrations"] = {}
    for app in apps:
        n = pathlib.Path(app["new"]).name
        code, M = migrate(rel_new, ROOT / app["new"], rel_old, src / app.get("old", app["new"]), ev_old[app["new"]], W / f"migration-{n}")
        R["migrations"][n] = {"ok": M["ok"], "steps": [(s["step"], s["result"]) for s in M["steps"]], "observed": M.get("observed")}
        expect(name, f"{app['new']} migrates state its accepted old artifact produced: every step passes", code == 0 and M["ok"], [(s["step"], s.get("detail", "")[-300:]) for s in M["steps"] if s["result"] != "pass"])

    WM = ROOT / S["wrong_migrations"]; X = yaml.safe_load((WM / "expected.yaml").read_text())
    for wname, want in X.items():
        base_app = next(a for a in apps if a["new"] == want["base"])
        cand = overlay(ROOT / want["base"], WM / wname, W / f"cand-wrong-{wname}")
        code, M = migrate(rel_new, cand, rel_old, src / base_app.get("old", base_app["new"]), ev_old[base_app["new"]], W / f"migration-wrong-{wname}")
        v = next((s for s in M["steps"] if s["step"].startswith("verify")), {})
        got = set(v.get("failing_tests") or []); need = set(want["failing_tests"]); may = set(want.get("may_also_fail") or [])
        R["migrations"]["wrong-" + wname] = {"ok": M["ok"], "steps": [(s["step"], s["result"]) for s in M["steps"]], "failing_tests": sorted(got)}
        expect(name, f"known-wrong migration {wname} is refused at verify for exactly its defect", code == 1 and v.get("result") == "fail" and need <= got <= need | may, sorted(got))
        if want.get("judged"):
            code, c, _ = judge(rel_new, cand, W / f"ev-wrong-{wname}")
            expect(name, f"known-wrong migration {wname} passes the ordinary judge: only the run with populated state catches it", code == 0, {k: c.get(k) for k in ("behavioral_assurance", "application_delivery")})


OUT.mkdir(parents=True, exist_ok=True)
for name, S in CFG["packs"].items():
    if only and name not in only: continue
    shutil.rmtree(OUT / name, ignore_errors=True)
    run_pack(name, S)
rec["ok"] = not failures; rec["failures"] = failures
(OUT / ("upgrades-record.json" if not only else f"upgrades-record-{'-'.join(only)}.json")).write_text(json.dumps(rec, indent=1, default=str))
print(f"upgrades: {'every expectation holds' if not failures else f'{len(failures)} FAILED'}")
sys.exit(0 if not failures else 1)
