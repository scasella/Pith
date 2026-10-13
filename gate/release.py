#!/usr/bin/env python3
"""gate/release.py — the platform release identity. FROZEN. Domain-free.

    python3 gate/release.py id    [--pack DIR]            print the release digest of the evaluator + the pack as they are on disk
    python3 gate/release.py dirs  [--pack DIR]            print the release's directories (gate/ and the pack's policy_dirs), one per line
    python3 gate/release.py build  --pack DIR --out OUT   materialise the release (gate/ + the pack) as a directory a judge can run from
    python3 gate/release.py seal  [--pack DIR]            write the frozen list and release.seal.json; run by the pack's maintainer only

A release is this evaluator (gate/) plus one contract pack: pack.yaml and the directories it lists as policy_dirs.
The release digest covers every one of those files (the frozen list is the per-file list). An evaluator run with
--expected-release <digest> refuses any platform whose digest differs, so the pin must be captured from a trusted
copy BEFORE an agent is given a workspace, and kept outside it.

One evaluator, several packs (v0.8.0). The repository root is the root pack (pack.yaml and the policy dirs it lists;
its frozen list is gate/frozen.sha256). Every other pack is a directory (--pack packs/<name>) holding its
own pack.yaml, policy dirs, frozen.sha256 and release.seal.json; `build` lays it out next to a copy of gate/ (its
frozen list becomes gate/frozen.sha256 of that release), so the judged layout is the same for every pack. The digest
of a pack directory equals the digest of the release built from it."""
import argparse, hashlib, json, pathlib, shutil, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import workspace as W

SKIP = ("frozen.sha256", "claims.json")


def _files(base, rel_dir):
    d = base / rel_dir
    if not d.exists(): return []
    return [(str(pathlib.Path(rel_dir) / p.relative_to(d)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(d.rglob("*"))
            if p.is_file() and p.name not in SKIP and not W.is_os_metadata(p) and not (W.CACHE_DIRS & set(p.relative_to(base).parts))]


def file_list(root=ROOT, pack=None):
    """[(release-relative path, sha256)]: pack.yaml, then gate/ (from `root`), then the pack's policy dirs (from `pack`)."""
    pack = pathlib.Path(pack or root)
    rows = [(W.PACK_FILE, W.sha(pack / W.PACK_FILE))] if (pack / W.PACK_FILE).exists() else []
    for d in W.load_pack_policy(pack)[0]:
        rows += _files(root if d == W.EVALUATOR_DIR else pack, d)
    return rows


def release_digest(root=ROOT, pack=None):
    h = hashlib.sha256()
    for path, sha in file_list(root, pack):
        h.update(path.encode()); h.update(sha.encode())
    return h.hexdigest()


def frozen_path(pack):
    pack = pathlib.Path(pack).resolve()
    return ROOT / "gate" / "frozen.sha256" if pack == ROOT else pack / "frozen.sha256"


def build(pack, out):
    """The release as a directory: gate/ (this evaluator), pack.yaml, release.seal.json and the pack's policy dirs."""
    pack, out = pathlib.Path(pack).resolve(), pathlib.Path(out)
    ign = shutil.ignore_patterns(*W.CACHE_DIRS, *W.OS_METADATA, "._*")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "gate", out / "gate", ignore=ign, dirs_exist_ok=True)
    for d in W.load_pack_policy(pack)[0][1:]:
        if (pack / d).exists(): shutil.copytree(pack / d, out / d, ignore=ign, dirs_exist_ok=True)
    for f in (W.PACK_FILE, W.SEAL): shutil.copy(pack / f, out / f)
    shutil.copy(frozen_path(pack), out / "gate" / "frozen.sha256")
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["id", "dirs", "build", "seal"]); ap.add_argument("--pack", default=None); ap.add_argument("--out", default=None)
    a = ap.parse_args(); pack = pathlib.Path(a.pack).resolve() if a.pack else ROOT
    if a.cmd == "id":
        print(release_digest(ROOT, pack))
    elif a.cmd == "dirs":
        print("\n".join(W.load_pack_policy(pack)[0]))
    elif a.cmd == "build":
        if not a.out: sys.exit("build needs --out")
        print(build(pack, a.out))
    elif a.cmd == "seal":
        import yaml
        rows = file_list(ROOT, pack); P = yaml.safe_load((pack / W.PACK_FILE).read_text())
        frozen_path(pack).write_text("".join(f"{sha}  {path}\n" for path, sha in rows))
        seal = {"format": 2, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pack": {k: P["pack"][k] for k in ("id", "version")},
                "policy_dirs": W.load_pack_policy(pack)[0], "files": len(rows), "release_digest": release_digest(ROOT, pack)}
        (pack / W.SEAL).write_text(json.dumps(seal, indent=2) + "\n")
        print(seal["release_digest"])


if __name__ == "__main__":
    main()
