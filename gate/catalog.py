#!/usr/bin/env python3
"""
gate/catalog.py — the catalog of maintained packs, and revocations. FROZEN. Domain-free.

    python3 gate/catalog.py check [--catalog catalog.yaml] [--revocations revocations.yaml] [--json]
        hold every catalog entry to its pack: the pack id, the release digest it lists is the sealed one, the stage it
        claims is the stage `gate/cli.py pack check` derives, every listed example, wrong candidate and document exists,
        its status is one of supported | deprecated | retired | demonstration, a released stage lists its reviews, and
        nothing it lists is revoked (unless retired)
    python3 gate/catalog.py revoked (--evidence DIR | --deployment FILE) [--key PUB ...] [--revocations revocations.yaml] [--json]
        does this evidence (or deployment record) rest on a revoked release or evaluator, or was it reviewed with a
        revoked key? Exit 1 if it does: its claims no longer stand (GOVERNANCE.md § When unsoundness is found)
    python3 gate/catalog.py pin [--catalog catalog.yaml]
        rewrite each entry's release_digest to the pack's sealed digest (after a reseal); `check` then confirms it

An entry is a statement about a pack (scope, assumptions, examples, wrong candidates, profiles, reference
implementations, evidence, upgrade policy, maintainers, reviews), never a certification that an application using
it is correct. Formats: pith.catalog/v1, pith.revocations/v1 (GOVERNANCE.md).
"""
import argparse, hashlib, json, pathlib, subprocess, sys
import yaml

HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(HERE))
import release as REL

STATUSES = ("supported", "deprecated", "retired", "demonstration")
REQUIRED = ("id", "path", "status", "stage", "release_digest", "scope", "assumptions", "examples", "wrong", "profiles",
            "reference_implementations", "evidence", "upgrade_policy", "maintainers", "reviews")


def load_revocations(path):
    p = pathlib.Path(path)
    if not p.exists(): return {"releases": [], "evaluators": [], "keys": [], "reviews": []}
    R = yaml.safe_load(p.read_text()) or {}
    if R.get("format") != "pith.revocations/v1": raise SystemExit(f"{p}: not pith.revocations/v1")
    return {k: R.get(k) or [] for k in ("releases", "evaluators", "keys", "reviews")}


def revoked_digests(R, kind): return {e["digest"]: e for e in R[kind]}


def sealed(path):
    d = (ROOT / path).resolve()
    s = json.loads((d / "release.seal.json").read_text())["release_digest"]
    return s, REL.release_digest(ROOT, None if d == ROOT else d)


def stage(path):
    r = subprocess.run([sys.executable, str(HERE / "cli.py"), "pack", "check", str(ROOT / path), "--json"], capture_output=True, text=True)
    try: return json.loads(r.stdout)
    except ValueError: return {"stage": "unknown", "errors": [r.stderr[-300:]]}


def check(cat, revs, as_json):
    C = yaml.safe_load(pathlib.Path(cat).read_text()); R = load_revocations(revs); out = []
    if C.get("format") != "pith.catalog/v1": out.append({"entry": None, "problem": "not pith.catalog/v1"})
    rv = revoked_digests(R, "releases")
    for e in C.get("packs", []):
        who = e.get("id"); bad = lambda m: out.append({"entry": who, "problem": m})
        for k in REQUIRED:
            if k not in e: bad(f"missing {k}")
        if any(k not in e for k in ("path", "id")): continue
        try: P = yaml.safe_load((ROOT / e["path"] / "pack.yaml").read_text())
        except OSError: bad(f"no pack.yaml at {e['path']}"); continue
        if P["pack"]["id"] != e["id"]: bad(f"path {e['path']} holds pack {P['pack']['id']}")
        if e.get("version") and str(P["pack"].get("version")) != str(e["version"]): bad(f"version {e['version']} but the pack is {P['pack'].get('version')}")
        seal, now = sealed(e["path"])
        if seal != now: bad("the pack is not sealed at its current content")
        if e.get("release_digest") != seal: bad(f"release_digest {str(e.get('release_digest'))[:16]} is not the sealed release {seal[:16]} (gate/catalog.py pin)")
        if e.get("status") not in STATUSES: bad(f"status must be one of {STATUSES}")
        S = stage(e["path"]); derived = str(S.get("stage", "")).split(" ")[0]
        if derived != e.get("stage"): bad(f"stage {e.get('stage')} but pack check derives {S.get('stage')}")
        if e.get("stage") == "released" and not e.get("reviews"): bad("released without a listed independent review")
        for k in ("examples", "wrong", "reference_implementations"):
            for x in e.get(k) or []:
                if not (ROOT / e["path"] / x).exists() and not (ROOT / x).exists(): bad(f"{k}: {x} does not exist")
        for x in [e.get("assumptions")] if isinstance(e.get("assumptions"), str) else []:
            if not (ROOT / e["path"] / x).exists() and not (ROOT / x).exists(): bad(f"assumptions: {x} does not exist")
        if seal in rv and e.get("status") != "retired": bad(f"release {seal[:16]} is revoked ({rv[seal].get('reason')}) but the entry is {e.get('status')}")
        if set(e.get("maintainers") or []) != set(P["pack"].get("maintainers") or []): bad("maintainers differ from the pack's")
    rep = {"format": "pith.catalog-check/v1", "ok": not out, "entries": len(C.get("packs", [])), "problems": out}
    if as_json: print(json.dumps(rep, indent=1))
    else:
        for p in out: print(f"[ERROR] {p['entry']}: {p['problem']}")
        print(f"catalog: {rep['entries']} entries, {'ok' if rep['ok'] else f'{len(out)} problems'}")
    return 0 if rep["ok"] else 1


def revoked(a):
    R = load_revocations(a.revocations); hits = []
    if a.evidence:
        E = json.loads((pathlib.Path(a.evidence) / "evidence.json").read_text()); rel, ev = E["release_digest"], E["evaluator_digest"]
    else:
        D = json.loads(pathlib.Path(a.deployment).read_text()); rel, ev = D["release_digest"], D.get("evaluator_digest")
    for kind, d in (("releases", rel), ("evaluators", ev)):
        e = revoked_digests(R, kind).get(d)
        if e: hits.append({"what": kind[:-1], "digest": d, "reason": e.get("reason"), "advisory": e.get("advisory"), "effect": e.get("effect")})
    for k in a.key or []:
        d = hashlib.sha256(pathlib.Path(k).read_bytes()).hexdigest(); e = revoked_digests(R, "keys").get(d)
        if e: hits.append({"what": "key", "digest": d, "reason": e.get("reason"), "advisory": e.get("advisory")})
    rep = {"format": "pith.revocation-check/v1", "revoked": bool(hits), "hits": hits}
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for h in hits: print(f"[REVOKED] {h['what']} {h['digest'][:16]}: {h['reason']} ({h.get('advisory')})")
        print("revoked: its claims no longer stand" if hits else "not revoked")
    return 1 if hits else 0


def pin(cat):
    """Rewrite each entry's release_digest line in place (comments and layout kept)."""
    p = pathlib.Path(cat); lines = p.read_text().splitlines(keepends=True); C = yaml.safe_load("".join(lines)); i = -1
    for n, ln in enumerate(lines):
        if ln.lstrip().startswith("- id:"): i += 1
        elif ln.strip().startswith("release_digest:") and i >= 0:
            e = C["packs"][i]; new = sealed(e["path"])[0]
            lines[n] = ln[:ln.index("release_digest:")] + f"release_digest: {new}\n"; print(f"{e['id']:<20} {e['path']:<22} {new}")
    p.write_text("".join(lines)); return 0


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--catalog", default=str(ROOT / "catalog.yaml")); c.add_argument("--revocations", default=str(ROOT / "revocations.yaml")); c.add_argument("--json", action="store_true")
    r = sub.add_parser("revoked"); g = r.add_mutually_exclusive_group(required=True); g.add_argument("--evidence"); g.add_argument("--deployment")
    r.add_argument("--key", action="append"); r.add_argument("--revocations", default=str(ROOT / "revocations.yaml")); r.add_argument("--json", action="store_true")
    p = sub.add_parser("pin"); p.add_argument("--catalog", default=str(ROOT / "catalog.yaml"))
    a = ap.parse_args()
    sys.exit(check(a.catalog, a.revocations, a.json) if a.cmd == "check" else revoked(a) if a.cmd == "revoked" else pin(a.catalog))


if __name__ == "__main__":
    main()
