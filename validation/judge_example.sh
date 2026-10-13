#!/usr/bin/env bash
# Judge an example (an overlay of agent-owned files) with the pristine release's gate.
#   validation/judge_example.sh [--pack packs/booking] examples/build-a ../evidence-build-a [--review r.json --reviewer-key k.pub]
# Without --pack the release is the repository root (the reservation pack); with it, the release is built from that
# pack directory and this repository's gate/ (gate/release.py build) into a fresh directory, which is the pristine copy.
set -euo pipefail
SEED="$(cd "$(dirname "$0")/.." && pwd)"
PACK=""; if [ "${1:-}" = "--pack" ]; then PACK="$(cd "$2" && pwd)"; shift 2; fi
EX="$(cd "$1" && pwd)"; OUT="$2"; shift 2
if [ -n "$PACK" ]; then
  PRISTINE="$(mktemp -d)"; python3 "$SEED/gate/release.py" build --pack "$PACK" --out "$PRISTINE" >/dev/null
  REL="$(python3 "$SEED/gate/release.py" id --pack "$PACK")"
else
  PRISTINE="$SEED"; REL="$(python3 "$SEED/gate/release.py" id)"
fi
CAND="$(mktemp -d)"
# the release = the evaluator (gate/) + the pack (pack.yaml and its policy_dirs)
for d in $(python3 "$PRISTINE/gate/release.py" dirs); do cp -r "$PRISTINE/$d" "$CAND/$d"; done
cp "$PRISTINE/pack.yaml" "$PRISTINE/release.seal.json" "$CAND/"
cp -r "$EX"/. "$CAND"/
rm -f "$CAND/claims-from-release.json" "$CAND"/*.example
echo "candidate assembled at $CAND (release $REL)"
python3 -I "$PRISTINE/gate/app_gate.py" --candidate "$CAND" --expected-release "$REL" --out "$OUT" "$@"
