"""
gate/workspace.py — digests, the deployment artifact and the judged workspace. FROZEN. Domain-free.

The judged workspace is a fresh directory holding the release's policy (the evaluator in gate/, pack.yaml and the
pack's policy_dirs, all from the trusted source) plus a COPY of the deployment artifact (app.manifest.yaml and the
pack's agent-owned dirs). The artifact digest covers every file in that copy; nothing is excluded by basename.

Existing projects (v0.9.0): when a pack allows the manifest key `include`, an adopting project lists the paths of its
own code that the entrypoints in the agent-owned dirs use (`include: [src/myapp]`); they are copied into the artifact at
the same relative paths and digested with it. An included path must be relative, inside the candidate, free of `..`,
and must not be or lie under a policy dir, gate/, or an evaluator-owned path. Nothing else of the project is copied.
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


def include_problems(include, policy_dirs, src):
    """Why each `include` entry is not acceptable (empty: all are)."""
    out = []
    if not isinstance(include, list): return ["include must be a list of relative paths"]
    for i in include:
        parts = pathlib.PurePosixPath(i).parts if isinstance(i, str) else ()
        if not isinstance(i, str) or not i or i.startswith("/") or "\\" in i or ".." in parts or not parts:
            out.append(f"{i!r}: must be a relative path inside the candidate, without '..'"); continue
        if parts[0] in policy_dirs or parts[0] in (PACK_FILE, SEAL, MANIFEST) or set(parts) & EVALUATOR_PATHS:
            out.append(f"{i!r}: names policy or an evaluator-owned path"); continue
        if not (pathlib.Path(src) / i).exists(): out.append(f"{i!r}: does not exist")
    return out


def copy_artifact(src, dst, policy_dirs, owned_dirs, include=()):
    """The deployment artifact: app.manifest.yaml + every file under the agent-owned dirs (and acceptable `include`
    paths), excluding only evaluator-owned paths."""
    dst.mkdir(parents=True)
    inc = [pathlib.PurePosixPath(i).parts for i in include if not include_problems([i], policy_dirs, src)]
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if not p.is_file() or is_os_metadata(p) or set(rel.parts) & EVALUATOR_PATHS or rel.parts[0] in policy_dirs: continue
        if rel.parts[0] in owned_dirs or str(rel) == MANIFEST or any(rel.parts[:len(i)] == i for i in inc):
            (dst / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dst / rel)


def assemble(candidate, policy_src, artifact_dir):
    """Build a fresh judged workspace from trusted policy + a copy of the candidate's artifact; returns its path."""
    candidate, policy_src = pathlib.Path(candidate), pathlib.Path(policy_src)
    policy_dirs, owned = load_pack_policy(policy_src)
    allow = yaml.safe_load((policy_src / PACK_FILE).read_text())["candidate"].get("manifest_allowlist", [])
    try: M = yaml.safe_load((candidate / MANIFEST).read_text()) or {}
    except Exception: M = {}
    include = M.get("include") if ("include" in allow and isinstance(M, dict) and isinstance(M.get("include"), list)) else []
    ws = pathlib.Path(tempfile.mkdtemp(prefix="judged-"))
    for d in policy_dirs:
        if (policy_src / d).exists(): shutil.copytree(policy_src / d, ws / d, ignore=shutil.ignore_patterns(*CACHE_DIRS, *OS_METADATA, "._*"))
    for f in (PACK_FILE, SEAL):
        if (policy_src / f).exists(): shutil.copy(policy_src / f, ws / f)
    copy_artifact(candidate, artifact_dir, policy_dirs, owned, include)
    shutil.copytree(artifact_dir, ws, dirs_exist_ok=True)
    return ws


def files_matching(root, globs):
    """{relative path: sha256} of the files under root matched by any glob ('dir/**' = everything under dir)."""
    root = pathlib.Path(root); out = {}
    for g in globs:
        # Path.glob("dir/**") yields files only from Python 3.13; before that, directories only. Spell it out.
        for p in root.glob(g + "/*" if g.endswith("**") else g):
            if p.is_file() and not is_os_metadata(p) and not (CACHE_DIRS & set(p.relative_to(root).parts)):
                out[str(p.relative_to(root))] = sha(p)
    return dict(sorted(out.items()))
