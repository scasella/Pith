#!/usr/bin/env bash
# Judge an example (an overlay of agent-owned files) with the pristine release's gate.
#   validation/judge_example.sh examples/build-a ../evidence-build-a [--review r.json --reviewer-key k.pub]
set -euo pipefail
SEED="$(cd "$(dirname "$0")/.." && pwd)"; EX="$(cd "$1" && pwd)"; OUT="$2"; shift 2
CAND="$(mktemp -d)"
# the release = the evaluator (gate/) + the pack (pack.yaml and its policy_dirs)
for d in $(python3 "$SEED/gate/release.py" dirs); do cp -r "$SEED/$d" "$CAND/$d"; done
cp "$SEED/pack.yaml" "$SEED/release.seal.json" "$CAND/"
cp -r "$EX"/. "$CAND"/
rm -f "$CAND/claims-from-release.json" "$CAND"/*.example
REL="$(python3 "$SEED/gate/release.py" id)"
echo "candidate assembled at $CAND (release $REL)"
python3 -I "$SEED/gate/app_gate.py" --candidate "$CAND" --expected-release "$REL" --out "$OUT" "$@"
