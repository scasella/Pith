"""validation/domain_free.py — the evaluator must not know the pack's domain. Scans every file under gate/ (except the
frozen list, which names pack files by path) for the pack's own vocabulary (pack.yaml:domain_vocabulary) and for
the ids of its contract records and checks. Exit 0 iff none occurs. Run in CI.

    python3 validation/domain_free.py [release-root]
"""
import pathlib, re, sys
import yaml

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent)
P = yaml.safe_load((root / "pack.yaml").read_text())
terms = set(P.get("domain_vocabulary", []))
terms |= {c["id"] for c in P.get("contracts", []) if len(c["id"]) > 2}          # P0, W1, ... are too short to search for meaningfully
terms |= {c["id"] for c in P.get("preflight", []) + P["checks"] if "." in c["id"]}
hits = []
for p in sorted((root / "gate").rglob("*")):
    if not p.is_file() or p.name == "frozen.sha256" or "__pycache__" in p.parts: continue
    text = p.read_text(errors="ignore")
    for t in sorted(terms):
        for m in re.finditer(re.escape(t), text, re.I if t.islower() else 0):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{p.relative_to(root)}:{line}: '{t}'")
print("\n".join(hits) if hits else f"ok: gate/ is free of the pack's {len(terms)} domain terms and ids")
sys.exit(1 if hits else 0)
