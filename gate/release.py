#!/usr/bin/env python3
"""gate/release.py — the platform release identity. FROZEN.

    python3 gate/release.py id          print the release digest of kernel/ + obligations/ + gate/ as they are on disk
    python3 gate/release.py seal        write release.seal.json (digest + per-file list); run by the seed publisher only

The release digest covers every frozen file (gate/frozen.sha256 is the per-file list; the digest is over that list
plus policy.yaml). An evaluator run with --expected-release <digest> refuses any platform whose digest differs,
so the pin must be captured from a trusted copy BEFORE an agent is given a workspace, and kept outside it."""
import hashlib, json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_DIRS = ["kernel", "obligations", "gate", "profiles"]

def file_list(root=ROOT):
    rows = []
    for d in POLICY_DIRS:
        if not (root / d).exists(): continue
        for p in sorted((root / d).rglob("*")):
            if p.is_file() and p.name not in ("frozen.sha256", "claims.json", ".DS_Store", "Thumbs.db", "desktop.ini") and not p.name.startswith("._") and not ({"__pycache__", ".pytest_cache", ".hypothesis"} & set(p.parts)):
                rows.append((str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest()))
    return rows

def release_digest(root=ROOT):
    h = hashlib.sha256()
    for path, sha in file_list(root):
        h.update(path.encode()); h.update(sha.encode())
    return h.hexdigest()

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "id"
    if cmd == "id":
        print(release_digest())
    elif cmd == "seal":
        rows = file_list()
        (ROOT / "gate" / "frozen.sha256").write_text("".join(f"{sha}  {path}\n" for path, sha in rows))
        seal = {"format": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "policy_dirs": POLICY_DIRS,
                "files": len(rows), "release_digest": release_digest()}
        (ROOT / "release.seal.json").write_text(json.dumps(seal, indent=2) + "\n")
        print(seal["release_digest"])
    else:
        sys.exit("usage: release.py id|seal")

if __name__ == "__main__":
    main()
