# AGENT.md — build the application around the proven core

You have cloned a seed. It contains a formally verified authorization core and the judges for
everything you build around it. There is no prose specification of the core; `INTENT.md` explains
it, `kernel/spec/AuthSpec.dfy` defines it, and `gate/app_gate.py` decides acceptance.

## What "done" means here

`python3 gate/app_gate.py` writes `app-claims.json` with three statuses:

- `behavioral_assurance` — rings 0–2, each claim scoped (proven / model-checked within bounds / not falsified).
- `application_delivery` — the required workflows demonstrated through your running service, UI served, SPEC complete.
- `human_approval` — approved / pending / rejected per required evaluation. You cannot change this.

You are done when the first two read `passed` (exit code 0) and the third reads `pending`. Every run
needs a fresh `--out` evidence directory outside your workspace; it receives the claims, a snapshot of the
judged application, and browser screenshots. A local run is advisory (it also reports `isolation: not enforced`,
which is expected on your machine); the authoritative result is produced
with `--policy-from <pristine release> --expected-release <pinned digest>` by the operator. `release_ready`
additionally needs a signed human review (`gate/review.py`) that you cannot produce. Nothing else counts,
including your own assessment of the code.

## What is here and who may change it

```
kernel/        proven core, adequacy suite, traces, audit channel, TCB, glossary          FROZEN
obligations/   what rings 1–3 must satisfy: TLA+ core actions + invariants + coverage,
               adapter harness, boundary harness + generator + monitor suite, lint, delivery  FROZEN
gate/          policy.yaml, app_gate.py, frozen.sha256                                      FROZEN
profiles/      shipped integration profile (sqlite); use it, or supply your own and pass the harness
app.manifest.yaml  only the allowlisted keys (name, profile, adapter_module, extra_tests, ui_entry)   YOURS
design/ service/ gen/out/ app/ ui/ (adapter/ if custom)   — the deployment artifact, digested whole   YOURS
INTENT.md CUSTOMIZATION.md   read them; they say what may vary and what may not
```

Editing a frozen file fails the gate before anything runs. If a frozen file is wrong, report it; for
the core, file a proof in `kernel/audit/`. Do not route around it. OS metadata files (`.DS_Store`,
`Thumbs.db`, `._*`) are ignored by every check, so you never need to mirror or clean the tree to run the
gate. Use the `.venv` that `bootstrap.sh` creates: one interpreter, one architecture.

## Work outward. Each ring green before the next.

**Ring 0 is done.** Run the gate first; it passes ring 0 and refuses at ring 1 telling you what is
missing. Read `kernel/core/claims.json`: `scope.does_not_cover` and
`runtime_assumptions_not_checked_by_compiled_code` are what rings 1–2 exist for.

**Ring 1, adapter.**
- Write `design/Design.tla` extending `CoreActions`: your concurrency, retries, loss, idempotency.
  Core state changes only via `CoreDecide(r, Available)`, `CoreReplay(r)`, `CoreRelease(r)`, `CoreCapture(r)` (two kernels: authorization and posting). Declare a
  `VARIABLE responses` (what each client has seen) and define `Spec`. Do NOT define `Idempotent`,
  `Consistent` or `CovRetry`: the frozen `MC.tla` binds them to your `responses`. The gate checks safety
  (including `DecideCorrect`), then that your model actually reaches retries, contention, declines under
  load, releases, and captures while another request is undecided. A model that models too little is refused.
- Use the shipped `sqlite` profile or set `profile: custom` and write your own adapter. A custom adapter is
  never imported by the judge: it is judged only through your running service by
  `obligations/service/lifecycle.py` (duplicate create, idempotent replay and conflicts, SIGKILL after commit
  then restart then retry, restart durability, event contract with `op_id`, hash chain and `state_after`,
  concurrency with readers). Validate inputs to the proof's domain before calling the core; the compiled
  core checks nothing.

**Ring 2, boundary.**
- Run `python3 obligations/boundary/generate.py` (the gate regenerates and diffs). Implement the API
  to `gen/out/openapi.yaml`; validate every request body against it before touching the adapter;
  emit the events in `gen/out/events.schema.json` in commit order. The service holds no logic.
- Provide `service/run.py`, the only way the judge ever runs your code:
  `python -I service/run.py --port <int> --db <path>` must serve the generated API on 127.0.0.1:<port>, the UI at `/`,
  persist to `<path>`, and exit on SIGTERM. It runs as a separate process with a scrubbed environment; `-I` means
  your script must put your project root on `sys.path` itself. The judge imports none of your Python, drives the
  service with its own client, and treats your stdout as application output, never as evidence.

**Ring 3, application.**
- Copy `obligations/app/SPEC.template.md` to `app/SPEC.md`; name workflows W1–W6 and evaluations E1–E3
  from `obligations/app/delivery.yaml`. Any sentence about authorization behaviour cites its obligation.
- Build the UI (served at `/`, path in `ui_entry`) to `obligations/app/UI-CONTRACT.md`: the listed
  `data-testid` affordances must exist and behave as described; layout, framework and styling are yours.
  The gate drives W1–W6 and a replay in a real browser at desktop and mobile widths. The UI talks only to
  the API and shows only numbers the API returned.
- Meet the interaction obligations I1–I6 in the same contract. The gate injects delayed, failed and lost
  responses and checks the effect on the service. In practice: treat the account field as a draft; bind every
  row and its actions to the account of the response that drew it; drop answers to superseded loads; keep a
  received decision when the refresh after it fails and mark the figures stale; show `UNKNOWN` (no response)
  and `REJECTED` (4xx) as outcomes distinct from a decision. `obligations/app/lib/pith-view.js` does all of
  this and is optional; `examples/build-a` uses it, `examples/build-b` and the desks do it by hand.
- Leave the evaluation table `(pending)`; approval comes only from an operator-signed attestation.
- Adapter events must be hash-chained and every `op.committed` must carry `state_after` (see the sqlite
  profile and `gen/out/events.schema.json`); the monitor checks continuity, not just event atoms.

## Rules the gate cannot check, which you follow anyway

- Never compute a decision or availability outside the core and the adapter; never define a core type by hand.
- If an obligation is satisfied without being exercised, say so in your report.
- Never weaken a check to make it pass; report a harness assertion you believe is wrong, with the failing example.
- Finish with: the gate output (and mode), every assumption not already in `kernel/tcb.yaml`, and anything frozen you believe is wrong.
