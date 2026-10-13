"""
gate/sandbox.py — the candidate's identity and limits. FROZEN. Part of the evaluator, not of any pack.

When the judge runs as root with SEED_CANDIDATE_UID set (the supported isolation profile, gate/isolation/), anything
that executes candidate code — a pack's service supervisor, the evaluator's isolation probe — drops to that
unprivileged user with no supplementary groups, in a new session, under the resource limits below. Without it the
candidate runs as the judge's own user; the evaluator reports that (isolation status) and release-readiness
requires an enforced profile.
"""
import os, subprocess

SCRUBBED_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
LIMITS = {"RLIMIT_CPU": 900, "RLIMIT_AS": 4 << 30, "RLIMIT_FSIZE": 512 << 20, "RLIMIT_NOFILE": 1024, "RLIMIT_NPROC": 256}


def candidate_identity():
    """(uid, gid) the candidate runs as, or None when no separate identity is configured (advisory)."""
    uid = os.environ.get("SEED_CANDIDATE_UID")
    if not uid: return None
    if os.geteuid() != 0: raise RuntimeError("SEED_CANDIDATE_UID is set but the judge is not root, so it cannot drop to that identity")
    return int(uid), int(os.environ.get("SEED_CANDIDATE_GID") or uid)


def limits(overrides=None):
    """LIMITS with a pack's overrides applied; None lifts a limit. A pack may need that for a runtime whose address-space
    guard regions are not memory use (V8 reserves ~10 GB of guard pages for WebAssembly, so RLIMIT_AS kills Node at
    start-up); memory is then bounded by the isolation profile's cgroup (gate/isolation/judge-isolated.sh --memory)."""
    out = dict(LIMITS); out.update(overrides or {})
    return {k: v for k, v in out.items() if v is not None}


def demote(ident, overrides=None):
    """preexec_fn: new session, rlimits, then drop to the candidate's identity (if any)."""
    import resource
    lim = limits(overrides)
    def fn():
        os.setsid()
        for name, v in lim.items():
            if name == "RLIMIT_NPROC" and not ident: continue        # per-user limit: only meaningful for a dedicated user
            resource.setrlimit(getattr(resource, name), (v, v))
        if ident:
            uid, gid = ident; os.setgroups([]); os.setgid(gid); os.setuid(uid)
            if os.getuid() == 0 or os.geteuid() == 0: raise RuntimeError("privilege drop failed")
    return fn


def scrubbed_env(extra=None):
    env = {k: os.environ[k] for k in SCRUBBED_ENV_KEYS if k in os.environ}; env.update(extra or {})
    return env


def run_as_candidate(argv, cwd, timeout=60, env_extra=None):
    """Run judge-owned code (the isolation probe) under the candidate's identity and limits; returns (code, stdout)."""
    r = subprocess.run(argv, cwd=cwd, env=scrubbed_env(env_extra), capture_output=True, text=True, timeout=timeout, preexec_fn=demote(candidate_identity()))
    return r.returncode, r.stdout


def run_as_candidate_full(argv, cwd, timeout=60, env_extra=None, limits=None):
    """Run a candidate's command once (a pack's CLI delivery, for instance) under the candidate's identity and limits;
    returns (code, stdout, stderr). A timeout is reported as code None. Added in v0.8.0 (M3)."""
    try:
        r = subprocess.run(argv, cwd=cwd, env=scrubbed_env(env_extra), capture_output=True, text=True, timeout=timeout, preexec_fn=demote(candidate_identity(), limits))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
