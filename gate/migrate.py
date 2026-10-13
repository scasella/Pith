#!/usr/bin/env python3
"""
gate/migrate.py — migrations as behavioural transformations, judged with populated state. FROZEN. Domain-free.

A release that changes a contract can ship migrations (pack.yaml `migrations`, each a spec in format
pith.migration/v1 inside the release's policy dirs). `run` judges one, end to end:

    python3 gate/migrate.py run --release NEW_RELEASE --candidate NEW_CANDIDATE \
        --old-release OLD_RELEASE --old-candidate OLD_CANDIDATE [--old-evidence OLD_EVIDENCE] --out DIR [--spec PATH] [--json]

  1. old artifact   with --old-evidence, the old candidate must be the artifact that evidence judged under the old
                    release (same artifact digest, same release digest): the state comes from what was accepted
  2. populate       the release's populate script drives the OLD artifact's own service to produce real state, and
                    records what that service acknowledged (results, requests in flight when it was killed)
  3. unrecognised   the candidate's migrate command must refuse state it does not recognise (exit non-zero)
  4. migrate        the candidate's migrate command transforms the state, as the candidate's identity
  5. migrate again  ... and running it a second time must succeed (a migration interrupted and retried is the norm)
  6. verify         the release's verify harness judges the NEW service on the migrated state against what was observed
  7. rollback       the spec's rollback policy is reported; `forward-only` is a stated restriction, not a check

The report (format pith.migration-report/v1, `migration-report.json` in --out) names the contract records the
migration establishes, the old and new release and artifact digests, each step's result and failure category, the
mapping, how old retries and in-flight requests behave, and the rollback policy. Exit 0 iff every step passed.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time
import yaml

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import workspace as W, evidence as EV, sandbox as SB, release as REL

FORMAT = "pith.migration/v1"; REPORT = "pith.migration-report/v1"


def sh(cmd, cwd, env=None, as_candidate=False, timeout=900):
    ident = SB.candidate_identity() if as_candidate else None
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                       env=SB.scrubbed_env(env or {}) if as_candidate else {**os.environ, **(env or {})},
                       preexec_fn=SB.demote(ident, {}) if as_candidate else None)
    return r.returncode, (r.stdout + r.stderr)


def run(a):
    out = pathlib.Path(a.out).resolve()
    if out.exists(): sys.exit(f"refused: {out} exists; use a fresh one")
    out.mkdir(parents=True)
    new_rel, old_rel = pathlib.Path(a.release).resolve(), pathlib.Path(a.old_release).resolve()
    new_ws = W.assemble(pathlib.Path(a.candidate).resolve(), new_rel, out / "artifact")
    old_ws = W.assemble(pathlib.Path(a.old_candidate).resolve(), old_rel, out / "old-artifact")
    P = yaml.safe_load((new_ws / W.PACK_FILE).read_text()); OP = yaml.safe_load((old_ws / W.PACK_FILE).read_text())
    spec_rel = a.spec or next((m["spec"] for m in P.get("migrations", []) if m.get("from") == OP["pack"].get("contract_version")), None)
    rep = {"format": REPORT, "ok": False, "steps": [],
           "from": {"pack": OP["pack"]["id"], "version": OP["pack"].get("version"), "contract_version": OP["pack"].get("contract_version"),
                    "release_digest": REL.release_digest(old_rel), "artifact_digest": W.digest_dir(out / "old-artifact")},
           "to": {"pack": P["pack"]["id"], "version": P["pack"].get("version"), "contract_version": P["pack"].get("contract_version"),
                  "release_digest": REL.release_digest(new_rel), "artifact_digest": W.digest_dir(out / "artifact")}}

    def step(name, ok, detail, category=None, **kw):
        rep["steps"].append({"step": name, "result": "pass" if ok else "fail", "detail": detail[-2000:] if isinstance(detail, str) else detail,
                             **({"category": category} if not ok else {}), **kw})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail.strip().splitlines()[-1][:160]}" if isinstance(detail, str) and detail.strip() else ""), file=sys.stderr)
        return ok

    def done():
        rep["ok"] = bool(rep["steps"]) and all(s["result"] == "pass" for s in rep["steps"])
        rep["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (out / "migration-report.json").write_text(json.dumps(rep, indent=1))
        shutil.rmtree(new_ws, ignore_errors=True); shutil.rmtree(old_ws, ignore_errors=True)
        print(f"migration {rep['from']['contract_version']} -> {rep['to']['contract_version']}: {'ok' if rep['ok'] else 'NOT ok'} ({out / 'migration-report.json'})", file=sys.stderr)
        return rep

    if not spec_rel or not (new_ws / spec_rel).is_file():
        step("migration spec", False, f"the new release declares no migration from {OP['pack'].get('contract_version')}", "contract_change"); return done()
    S = yaml.safe_load((new_ws / spec_rel).read_text())
    if S.get("format") != FORMAT or S["from"].get("contract_version") != OP["pack"].get("contract_version") or S["to"].get("contract_version") != P["pack"].get("contract_version"):
        step("migration spec", False, f"{spec_rel} is not a {FORMAT} spec from {OP['pack'].get('contract_version')} to {P['pack'].get('contract_version')}", "contract_change"); return done()
    rep.update({"spec": spec_rel, "records": S.get("records", []), "mapping": S.get("mapping"), "retries": S.get("retries"),
                "in_flight": S.get("in_flight"), "rollback": S.get("rollback"), "state": S.get("state")})
    py = sys.executable; pytest = P.get("pytest", "{python} -m pytest -q").replace("{python}", py).replace("{root}", str(new_ws))
    state = out / "state"; state.mkdir(); observed = out / "observed.json"
    sub = lambda c: c.replace("{python}", py).replace("{pytest}", pytest).replace("{old}", str(old_ws)).replace("{state}", str(state)).replace("{observed}", str(observed))

    if a.old_evidence:
        E = EV.load(a.old_evidence)
        same = E["artifact_digest"] == rep["from"]["artifact_digest"] and E["release_digest"] == rep["from"]["release_digest"]
        accepted = all(ready(OP, n, v) for n, v in (E.get("statuses") or {}).items() if n in (OP.get("statuses") or {}))
        if not step("old artifact is the judged one", same and accepted,
                    f"evidence {E['digest'][:16]}: artifact {E['artifact_digest'][:16]} vs {rep['from']['artifact_digest'][:16]}, release {E['release_digest'][:16]} vs {rep['from']['release_digest'][:16]}, statuses {E.get('statuses')}",
                    "infrastructure" if not same else "evidence_missing"): return done()
        rep["from"]["evidence_digest"] = E["digest"]

    code, o = sh(sub(S["populate"]), new_ws)
    if not step("populate: the old artifact's service produced state", code == 0 and observed.is_file(), o, "infrastructure"): return done()
    rep["observed"] = json.loads(observed.read_text())

    if S.get("unrecognised"):
        bad = pathlib.Path(tempfile.mkdtemp(prefix="unrecognised-")); before = {}
        for f, text in S["unrecognised"].get("files", {}).items(): (bad / f).write_text(text); before[f] = text
        code, o = sh(sub(S["migrate"]).replace(str(state), str(bad)), new_ws, as_candidate=True)
        kept = all((bad / f).read_text() == t for f, t in before.items())
        step("migrate refuses unrecognised state", code != 0 and kept, (o or "") + f"\nexit {code}; state {'unchanged' if kept else 'CHANGED'}", "violation")
        shutil.rmtree(bad, ignore_errors=True)

    ident = SB.candidate_identity()
    if ident:
        for p in [state, *state.rglob("*")]: os.chown(p, *ident)
    code, o = sh(sub(S["migrate"]), new_ws, as_candidate=True)
    if not step("migrate", code == 0, o, "violation" if code not in (126, 127) else "toolchain_unavailable"): return done()
    code, o = sh(sub(S["migrate"]), new_ws, as_candidate=True)
    if not step("migrate again (interrupted and retried)", code == 0, o, "violation"): return done()
    rep["migrated_state_digest"] = W.digest_dir(state)

    code, o = sh(sub(S["verify"]), new_ws, env={"PITH_MIGRATION_STATE": str(state), "PITH_MIGRATION_OBSERVED": str(observed)})
    failing = sorted(set(re.findall(r"FAILED \S+::(\w+)", o)))
    step("verify: the new service on the migrated state", code == 0, o, "violation", failing_tests=failing)
    rb = S.get("rollback") or {}
    step("rollback policy stated", rb.get("policy") in ("forward-only", "reversible") and bool(rb.get("why")), f"{rb.get('policy')}: {str(rb.get('why', '')).strip()}", "evidence_missing")
    return done()


def ready(P, name, value):
    """Whether a status value meets the pack's ready condition (as gate/app_gate.py decides it)."""
    cond = P["statuses"][name]["ready"]
    return isinstance(value, str) and (value.startswith(cond["startswith"]) if "startswith" in cond else value == cond["equals"])


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    for k in ("--release", "--candidate", "--old-release", "--old-candidate", "--out"): r.add_argument(k, required=True)
    r.add_argument("--old-evidence"); r.add_argument("--spec"); r.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = run(a)
    if a.json: print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
