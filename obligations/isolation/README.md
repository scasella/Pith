# Evaluator isolation — the supported profile

A process boundary is not a sandbox. Until v0.5.0 the candidate's service ran as the judge's own user, so a hostile
`service/run.py` could read the evidence directory, rewrite the judged copy of the gate, or reach the network; the
release said so and left operational isolation to the operator. From v0.6.0 the release ships one supported
isolation profile and the gate **observes** whether it is in force rather than taking it on trust.

## What the gate does on every run

1. Before any candidate code runs, `probe.py` is executed under the candidate's identity and resource limits. It
   tries to list and write the evidence directory, write into `kernel/`, `obligations/` and `gate/` of the judged
   copy, append to `gate/app_gate.py`, read any path in `SEED_PROTECTED_PATHS`, and open connections to
   `1.1.1.1:443` and `github.com:443`.
2. `app-claims.json` records `isolation.status` (`enforced` only if a separate identity was configured **and** every
   probe was denied), the profile, the identity, the resource limits, and every probe result.
3. The candidate's service runs as `SEED_CANDIDATE_UID` (no supplementary groups, its own process group, rlimits on
   CPU, address space, file size, open files and processes). It may write only its database directory.
4. With `SEED_BROWSER_LAUNCHER=obligations/isolation/browser_as.py`, Chromium runs as `SEED_BROWSER_UID`, so the
   candidate's JavaScript cannot read the evidence or the judge's files even if it escapes the renderer.
5. `release_ready` requires `isolation.status == enforced`, and a contained browser: Chromium's own sandbox, or the
   separate browser user under the enforced profile. `release_ready_missing` lists whatever is absent.

A run without a separate identity still works. It is labelled advisory, `isolation.status` is `not enforced`, and
the report names what the candidate could reach.

## The supported environment: `judge-isolated.sh` + `Containerfile`

```bash
RELEASE="$(python3 gate/release.py id)"              # from your trusted copy, before any agent sees a workspace
obligations/isolation/judge-isolated.sh /path/to/pristine /path/to/candidate ../evidence-007 "$RELEASE"
```

Linux with docker or podman. The image pins Python, Dafny (by digest), TLC (by digest), the Python packages and
Playwright's Chromium. The launcher adds the runtime restrictions:

| Restriction | Mechanism | Observed by |
|---|---|---|
| no network | `--network none` | probe: `connect …` denied |
| policy and candidate immutable | read-only mounts, `--read-only` root, judge-owned copy in tmpfs | probe: `write policy (…)`, `modify gate code` denied |
| evidence private to the judge | only writable mount, mode 0700, root-owned | probe: `read/write evidence directory` denied |
| candidate unprivileged | uid 10001, no groups, `no-new-privileges`, capabilities dropped | probe: `runs as root` denied |
| browser unprivileged | uid 10002 via `browser_as.py` | report: `browser_user` |
| bounded resources | `--memory`, `--cpus`, `--pids-limit`, a 4 GiB `/tmp` tmpfs, per-candidate rlimits (incl. `RLIMIT_FSIZE`) | recorded, not probed |
| no review credentials | reviewer keys are never mounted; verify attestations afterwards with `gate/review.py` | probe: `SEED_PROTECTED_PATHS` |

There is deliberately no container-wide `--ulimit fsize`: .NET (Dafny) reserves its executable memory as a
large memfd and dies with SIGXFSZ under any file-size limit. The candidate's own processes get `RLIMIT_FSIZE`.

Evidence files are written by root inside the container; with rootful docker they are root-owned on the host.

## What it does not cover

- Kernel or container-runtime escapes. The profile is defence in depth against a candidate, not against a
  privileged attacker on the host.
- Timing side channels, and denial of service beyond the configured limits.
- Third-party checkers. Running a checker in another process does not establish that it checks the right property;
  every checker the gate runs is part of the frozen, digested release.
- Candidate builds. The candidate has no build or dependency-install step in this release; it runs on the image's
  pinned interpreter and packages. A release that adds one must run it under this profile.

## Fast local mode

`python3 gate/app_gate.py --out …` remains the quick advisory loop for agents. Its limitations are visible in the
report: `gate_mode: local (advisory)`, `isolation.status: not enforced`, and `release_ready_missing`. An unavailable
verifier, browser, or isolation capability is a blocker or an unmet requirement, never a substitute.
