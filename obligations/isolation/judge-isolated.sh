#!/usr/bin/env bash
# obligations/isolation/judge-isolated.sh — run the authoritative judge inside the supported isolation profile. FROZEN.
#
#   obligations/isolation/judge-isolated.sh <pristine-release> <candidate> <evidence-out> <expected-release> [gate args...]
#
# Host requirements: Linux with docker or podman. What the profile enforces, and what the gate then OBSERVES with
# obligations/isolation/probe.py before any candidate code runs:
#   * no network at all (--network none): the candidate and its page reach nothing but 127.0.0.1;
#   * the pristine release and the candidate are mounted read-only; the judge works on its own copy in a tmpfs;
#   * the evidence directory is the only writable mount, owned by the judge (root in the container), mode 0700;
#   * the candidate's service runs as uid 10001 and the browser as uid 10002, neither able to read the evidence or
#     write the judge's files; reviewer keys are never mounted (attestations are verified afterwards, outside);
#   * memory, CPU, process-count and file-size limits (cgroup and rlimit);
#   * all capabilities dropped except those the judge needs to hand files to and switch to the two users.
# The candidate has no build or dependency-install step in this release: it runs on the image's pinned interpreter
# and packages. A release that adds one must run it under this same profile.
set -euo pipefail
[ $# -ge 4 ] || { sed -n '4,4p' "$0"; exit 2; }
PRISTINE="$(cd "$1" && pwd)"; CAND="$(cd "$2" && pwd)"; OUT="$3"; REL="$4"; shift 4
ENGINE="${CONTAINER_ENGINE:-$(command -v docker || command -v podman)}"
TAG="pith-judge:$(sha256sum "$PRISTINE/obligations/isolation/Containerfile" | cut -c1-16)"
"$ENGINE" image inspect "$TAG" >/dev/null 2>&1 || "$ENGINE" build -q -t "$TAG" -f "$PRISTINE/obligations/isolation/Containerfile" "$PRISTINE/obligations/isolation"
[ -e "$OUT" ] && { echo "refused: evidence directory $OUT exists; use a fresh one" >&2; exit 1; }
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
exec "$ENGINE" run --rm --network none --read-only --tmpfs /tmp:rw,exec,size=4g \
  --memory 6g --cpus 2 --pids-limit 1024 --ulimit fsize=2147483648 \
  --cap-drop ALL --cap-add CHOWN --cap-add SETUID --cap-add SETGID --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add KILL \
  --security-opt no-new-privileges \
  -v "$PRISTINE":/pith:ro -v "$CAND":/candidate:ro -v "$OUT":/evidence \
  "$TAG" python -I /pith/gate/app_gate.py --candidate /candidate --expected-release "$REL" --out /evidence/run "$@"
