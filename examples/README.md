# Examples

Each example is an overlay of agent-owned files only (`design/`, `service/`, `gen/`, `app/`, `ui/`, optionally
`adapter/`, and `app.manifest.yaml`). The seed supplies everything else. `claims-from-release.json` is the
pristine judge's output for that overlay under the sealed release (advisory isolation and an unsandboxed browser
in the recording environment, hence `release_ready: false`; `release_ready_missing` says so).

| example | integration | design | UI | origin |
|---|---|---|---|---|
| `build-a` | shipped sqlite profile | client phases with lost responses and resends | web console on the optional `pith-view.js` client-state library | reference |
| `build-b` | custom JSON-file adapter (`profile: custom`) | single-writer queue with resends | plain terminal-style page, state handled by hand | reference |
| `club-desk` | shipped sqlite profile | build-a's design | numbered first-time-treasurer layout | reference-assisted agent build, corrected after review (v0.6.0) |
| `office-desk` | shipped sqlite profile | build-a's design | compact two-column workbench, keyboard-first | reference-assisted agent build, corrected after review (v0.6.0) |
| `archive/agent-build-hold-desk-v0.4.1` | shipped sqlite profile | decide/lose/replay | web console | first unassisted agent build (macOS), v0.4.1 only, not judged by CI |

## Known-wrong fixtures: `wrong/`

`wrong/club-desk` and `wrong/office-desk` are the two desk applications **as submitted** to the 2026-10-13 review,
with their UI logic unchanged. The only edit is contract markup the v0.6.0 UI contract names
(`btn-load`, `loaded-account`, `data-account-id` on rows), recorded line by line in each `ui.contract-markup.diff`,
so that the judge can locate the elements and refuse them for their actual defects rather than for missing ids.
`wrong/expected.yaml` lists the exact interaction obligations each must fail and the review finding behind each;
`validation/judge_wrong.py` (run in CI) checks that the pristine gate reaches exactly that verdict. The corrected
applications above pass the same obligations.

What changed in the corrected desks: the account field became a draft and rows carry the account that drew them;
loads are sequenced so late answers are dropped; a decision is shown with its own account and request and survives
a failed refresh, which now marks the figures stale; no-response, refusal and decision are distinct outcomes.
Club Desk's activity panel now shows only the loaded account. Office Desk's static "Service connected" label is now
a live indicator driven by actual responses. Services, designs and specs are as submitted.

Judge one: `validation/judge_example.sh examples/build-a ../evidence-a`. To approve one, sign an attestation for
the `artifact_digest` in its claims with `gate/review.py` and pass `--review`/`--reviewer-key`
(`build-a/operator-reviewer.pub.example` is the public key used in the validation record).
