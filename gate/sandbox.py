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


def demote(ident):
    """preexec_fn: new session, rlimits, then drop to the candidate's identity (if any)."""
    import resource
    def fn():
        os.setsid()
        for name, v in LIMITS.items():
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
