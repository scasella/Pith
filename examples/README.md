# Examples

Each example is an overlay of agent-owned files only (`design/`, `service/`, `gen/`, `app/`, `ui/`, optionally
`adapter/`, and `app.manifest.yaml`). The seed supplies everything else. `claims-from-release.json` is the
pristine judge's output for that overlay under the sealed release (browser unsandboxed in the recording
environment, hence `release_ready: false`).

| example | integration | design | UI | origin |
|---|---|---|---|---|
| `build-a` | shipped sqlite profile | client phases with lost responses and resends | web console | reference |
| `build-b` | custom JSON-file adapter (`profile: custom`) | single-writer queue with resends | plain terminal-style page | reference |
| `agent-build-hold-desk` | shipped sqlite profile | decide/lose/replay, no client phases | web console | first unassisted agent build (macOS), unchanged |

Judge one: `validation/judge_example.sh examples/build-a ../evidence-a`. To approve one, sign an attestation for
the `artifact_digest` in its claims with `gate/review.py` and pass `--review`/`--reviewer-key`
(`build-a/operator-reviewer.pub.example` is the public key used in the validation record).
