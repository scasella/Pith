#!/usr/bin/env python3
"""gate/release.py — the platform release identity. FROZEN. Domain-free.

    python3 gate/release.py id          print the release digest of the evaluator + the pack as they are on disk
    python3 gate/release.py dirs        print the release's directories (gate/ and the pack's policy_dirs), one per line
    python3 gate/release.py seal        write gate/frozen.sha256 and release.seal.json; run by the seed publisher only

A release is this evaluator (gate/) plus one contract pack: pack.yaml and the directories it lists as policy_dirs.
The release digest covers every one of those files (gate/frozen.sha256 is the per-file list). An evaluator run with
--expected-release <digest> refuses any platform whose digest differs, so the pin must be captured from a trusted
copy BEFORE an agent is given a workspace, and kept outside it."""
import hashlib, json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import workspace as W

def file_list(root=ROOT):
    rows = [(W.PACK_FILE, W.sha(root / W.PACK_FILE))] if (root / W.PACK_FILE).exists() else []
    for d in W.load_pack_policy(root)[0]:
        if not (root / d).exists(): continue
        for p in sorted((root / d).rglob("*")):
            if p.is_file() and p.name not in ("frozen.sha256", "claims.json") and not W.is_os_metadata(p) and not (W.CACHE_DIRS & set(p.parts)):
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
    elif cmd == "dirs":
        print("\n".join(W.load_pack_policy(ROOT)[0]))
    elif cmd == "seal":
        import yaml
        rows = file_list(); P = yaml.safe_load((ROOT / W.PACK_FILE).read_text())
        (ROOT / "gate" / "frozen.sha256").write_text("".join(f"{sha}  {path}\n" for path, sha in rows))
        seal = {"format": 2, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pack": {k: P["pack"][k] for k in ("id", "version")},
                "policy_dirs": W.load_pack_policy(ROOT)[0], "files": len(rows), "release_digest": release_digest()}
        (ROOT / "release.seal.json").write_text(json.dumps(seal, indent=2) + "\n")
        print(seal["release_digest"])
    else:
        sys.exit("usage: release.py id|dirs|seal")

if __name__ == "__main__":
    main()
