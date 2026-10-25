"""
gate/pack.py — load, validate and expand a contract pack (pack.yaml). FROZEN. Domain-free.

The evaluator reads WHAT to check from the pack and only HOW to run each kind of check from gate/kinds.py.
Format: docs/rfc/0001-contract-packs-and-evidence.md § Pack manifest.
"""
import pathlib, re
import yaml

FORMAT = "pith.pack/v1"
KINDS = {"command", "files_present", "source_rules", "tlc", "regenerated", "manifest_choice", "manifest_commands", "adapter", "attestation"}
METHODS = {"proof", "model-check", "test", "browser", "review", "structural", "policy"}
STATUS_RULES = {"all_pass", "from_check"}
ROUTES = ("presentation", "integration", "behavioral")              # gate/change.py
CATEGORIES = ("violation", "not_exercised", "evidence_missing", "toolchain_unavailable", "contract_change", "infrastructure")   # = gate/packet.py


class PackError(Exception):
    pass


def load(root):
    root = pathlib.Path(root)
    P = yaml.safe_load((root / "pack.yaml").read_text())
    validate(P, root)
    return P


def validate(P, root):
    def need(cond, msg):
        if not cond: raise PackError(msg)
    need(isinstance(P, dict) and P.get("format") == FORMAT, f"pack.yaml format must be {FORMAT}")
    for k in ("pack", "policy_dirs", "candidate", "statuses", "checks", "refusal_status", "completion_status"):
        need(k in P, f"pack.yaml lacks {k}")
    need(all(k in P["pack"] for k in ("id", "version")), "pack.id and pack.version are required")
    need("gate" not in P["policy_dirs"], "gate/ is the evaluator's; a pack cannot list it")
    need(not set(P["policy_dirs"]) & set(P["candidate"]["owned_dirs"]), "a directory cannot be both policy and agent-owned")
    seen = set()
    for c in P.get("preflight", []) + P["checks"]:
        need(isinstance(c, dict) and c.get("id") and c.get("name") and c.get("area"), f"check without id/name/area: {c}")
        need(c["id"] not in seen, f"duplicate check id {c['id']}")
        need(c.get("kind") in KINDS, f"{c['id']}: unknown kind {c.get('kind')}")
        need(c.get("method") in METHODS, f"{c['id']}: method must be one of {sorted(METHODS)}")
        need(c.get("status") is None or c["status"] in P["statuses"], f"{c['id']}: unknown status {c.get('status')}")
        for d in c.get("depends_on", []):
            need(d in seen, f"{c['id']}: depends_on {d} must name an earlier check")
        if c.get("each"):
            need(isinstance(c["each"], dict) and len(set(c["each"]) & {"list", "glob"}) == 1, f"{c['id']}: each needs exactly one of list, glob")
        if c["kind"] == "command" and "expect_exit" in c:
            need(c["expect_exit"] in ("zero", "nonzero"), f"{c['id']}: expect_exit must be zero or nonzero")
        if "failure_category" in c:
            need(c["failure_category"] in CATEGORIES, f"{c['id']}: failure_category must be one of {CATEGORIES}")
        need(c.get("about", "candidate") in ("candidate", "release"), f"{c['id']}: about must be candidate or release")
        if c["kind"] == "adapter":
            need(pathlib.PurePosixPath(c["adapter"]).parts[0] in P["policy_dirs"], f"{c['id']}: an adapter must be pack policy code")
        seen.add(c["id"])
    for name, s in P["statuses"].items():
        need(s.get("rule") in STATUS_RULES, f"status {name}: rule must be one of {sorted(STATUS_RULES)}")
        if s["rule"] == "from_check": need(s.get("check") in seen, f"status {name}: check {s.get('check')} not declared")
        need(isinstance(s.get("ready"), dict), f"status {name}: ready condition required")
    need(P["refusal_status"] in P["statuses"] and P["completion_status"] in P["statuses"], "refusal_status/completion_status must be statuses")
    ids = {c["id"] for c in P.get("contracts", [])}
    for c in P.get("contracts", []):
        for v in c.get("verified_by", []): need(v in seen, f"contract {c['id']}: verified_by {v} is not a check")
    for c in P["checks"]:
        for e in c.get("establishes", []): need(e in ids, f"{c['id']}: establishes {e}, which has no contract record")
    for c in P.get("contracts", []):
        need(c.get("change") in (None, *ROUTES), f"contract {c['id']}: change must be one of {ROUTES}")
    for r in P.get("change_routes", []):
        need(isinstance(r.get("paths"), list) and r["paths"] and r.get("route") in ROUTES, f"change_routes: each entry needs paths and a route in {ROUTES}")
    for x in P.get("partitions", []):                               # gate/change.py merge (v0.13.0); optional
        need(isinstance(x, dict) and x.get("id") and isinstance(x.get("paths"), list) and x["paths"], "partitions: each needs an id and paths")
    need(len({x.get("id") for x in P.get("partitions", [])}) == len(P.get("partitions", [])), "partitions: duplicate id")
    tr = P.get("traces")                                            # gate/packet.py, gate/trace.py (v0.13.0); optional
    if tr is not None:
        need(isinstance(tr, dict) and all(isinstance(tr.get(k), str) for k in tr if k in ("oracle", "render", "render_file", "replay")) and tr.get("oracle"),
             "traces: oracle (a command), and optionally render, render_file and replay")
    pk = P.get("packet")
    if pk is not None:
        need(isinstance(pk, dict) and isinstance(pk.get("vocabulary", []), list), "packet: vocabulary must be a list of the pack's documents")
    rt = P.get("redteam")                                           # gate/redteam.py (v0.13.0); optional
    if rt is not None:
        need(isinstance(rt, dict) and (rt.get("examples") or rt.get("spec")), "redteam: needs an examples or a spec target")
        if rt.get("examples"): need(isinstance(rt["examples"].get("base"), str) and isinstance(rt["examples"].get("mutate", []), list), "redteam.examples: base (a reference example) and mutate (globs)")
        if rt.get("spec"): need(all(rt["spec"].get(k) for k in ("reference", "accepts", "violates", "wrong_dir")), "redteam.spec: reference, accepts, violates and wrong_dir")


def expand(P, root, manifest, section="checks"):
    """Concrete checks for this workspace: `when` applied, `each` lists and manifest command lists expanded.
    Each concrete check has `id` (unique), `group` (the declared id) and `name` (placeholders filled)."""
    root = pathlib.Path(root); out = []
    defaults = {c["key"]: c.get("default") for c in P.get("preflight", []) if c["kind"] == "manifest_choice"}
    m = {k: (manifest.get(k) if manifest.get(k) is not None else defaults.get(k)) for k in set(manifest) | set(defaults)}
    for c in P.get(section, []):
        if not all(m.get(k) == v for k, v in ((c.get("when") or {}).get("manifest") or {}).items()): continue
        items = None
        if c.get("each", {}).get("glob"):                      # one check per file the glob matches in the judged workspace
            items = sorted(str(p.relative_to(root)) for p in root.glob(c["each"]["glob"]) if p.is_file())
        elif c.get("each"):
            src = c["each"]["list"]; base = root / c["copy"]["from"] / src if c.get("copy") else root / src
            items = base.read_text().split() if base.exists() else []
        elif c["kind"] == "manifest_commands":
            items = list(manifest.get(c["key"]) or [])
        if items is None:
            out.append({**c, "group": c["id"]})
        else:
            for it in items:
                out.append({**c, "group": c["id"], "id": f"{c['id']}/{_slug(it)}", "name": c["name"].replace("{item}", it), "item": it})
    return out


def _slug(s): return re.sub(r"[^A-Za-z0-9_.-]+", "-", s).strip("-")[:60] or "item"
