"""
gate/workspace.py — digests, the deployment artifact and the judged workspace. FROZEN. Domain-free.

The judged workspace is a fresh directory holding the release's policy (the evaluator in gate/, pack.yaml and the
pack's policy_dirs, all from the trusted source) plus a COPY of the deployment artifact (app.manifest.yaml and the
pack's agent-owned dirs). The artifact digest covers every file in that copy; nothing is excluded by basename.
"""
import hashlib, pathlib, shutil, tempfile
import yaml

EVALUATOR_DIR = "gate"
PACK_FILE = "pack.yaml"
MANIFEST = "app.manifest.yaml"
SEAL = "release.seal.json"
EVALUATOR_PATHS = {"app-claims.json", SEAL, ".tools", ".venv", "evidence", ".git", "__pycache__", ".hypothesis", ".pytest_cache", "states"}
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".hypothesis"}
OS_METADATA = {".DS_Store", "Thumbs.db", "desktop.ini"}          # written by file browsers, not by anyone; ignored everywhere


def is_os_metadata(p): return p.name in OS_METADATA or p.name.startswith("._")


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def digest_dir(d):
    """Digest of EVERY file under d, by relative path. No exclusions."""
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(d).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode()); h.update(sha(p).encode())
    return h.hexdigest()


def load_pack_policy(root):
    """(policy_dirs, owned_dirs) of the pack at root; policy_dirs always starts with the evaluator's own directory."""
    P = yaml.safe_load((pathlib.Path(root) / PACK_FILE).read_text())
    return [EVALUATOR_DIR] + [d for d in P["policy_dirs"] if d != EVALUATOR_DIR], P["candidate"]["owned_dirs"]


def copy_artifact(src, dst, policy_dirs, owned_dirs):
    """The deployment artifact: app.manifest.yaml + every file under the agent-owned dirs, excluding only evaluator-owned paths."""
    dst.mkdir(parents=True)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if not p.is_file() or is_os_metadata(p) or set(rel.parts) & EVALUATOR_PATHS or rel.parts[0] in policy_dirs: continue
        if rel.parts[0] in owned_dirs or str(rel) == MANIFEST:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dst / rel)


def assemble(candidate, policy_src, artifact_dir):
    """Build a fresh judged workspace from trusted policy + a copy of the candidate's artifact; returns its path."""
    candidate, policy_src = pathlib.Path(candidate), pathlib.Path(policy_src)
    policy_dirs, owned = load_pack_policy(policy_src)
    ws = pathlib.Path(tempfile.mkdtemp(prefix="judged-"))
    for d in policy_dirs:
        if (policy_src / d).exists(): shutil.copytree(policy_src / d, ws / d, ignore=shutil.ignore_patterns(*CACHE_DIRS, *OS_METADATA, "._*"))
    for f in (PACK_FILE, SEAL):
        if (policy_src / f).exists(): shutil.copy(policy_src / f, ws / f)
    copy_artifact(candidate, artifact_dir, policy_dirs, owned)
    shutil.copytree(artifact_dir, ws, dirs_exist_ok=True)
    return ws


def files_matching(root, globs):
    """{relative path: sha256} of the files under root matched by any glob ('dir/**' = everything under dir)."""
    root = pathlib.Path(root); out = {}
    for g in globs:
        for p in root.glob(g):
            if p.is_file() and not is_os_metadata(p) and not (CACHE_DIRS & set(p.relative_to(root).parts)):
                out[str(p.relative_to(root))] = sha(p)
    return dict(sorted(out.items()))
