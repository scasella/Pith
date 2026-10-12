# core-seed

**A formally verified application core that a coding agent builds an application around, with a judge that
says exactly which properties of the result are proved, model-checked, tested, or awaiting human review.**

The seed contains a proven authorization-and-reservation kernel (Dafny), the obligations every surrounding
layer must satisfy (TLA+ invariants, black-box harnesses, a UI contract), and an evaluator that runs the
candidate as a separate process and never trusts its output. An agent clones the repository, reads
`AGENT.md`, and builds the design model, service, and user interface. The gate decides when it is done.

> Status: research prototype, v0.4.1. The method and the judge have been through four external reviews and
> one unassisted agent build (see `docs/VALIDATION.md`). It is not a payment system; no funds move. Read
> `INTENT.md` for what the core means and `kernel/tcb.yaml` for what a green result rests on.

## What is in the box

```
kernel/        the proven core: Dafny spec + implementation + proof, Python translation reproduced in the gate,
               adequacy suite (wrong implementations the spec must reject), signed-trace record, audit channel, TCB
obligations/   what the rest of the app must satisfy: TLA+ core actions, invariants and coverage checks for
               agent-written designs; black-box lifecycle and boundary harnesses; generated API/event/monitor
               artifacts; UI contract and real-browser workflow tests; prose-spec lint
profiles/      a shipped, frozen SQLite integration profile (replaceable: a custom profile is judged black-box)
gate/          the judge: policy, release seal, review attestations, app_gate.py
examples/      three conforming builds (two reference, one by an unassisted agent): agent-owned files only
docs/          validation record, research background, the hybrid-spec essay this grew out of
```

Everything under `kernel/`, `obligations/`, `gate/` and `profiles/` is frozen and hash-listed; the release has
an identity (`gate/release.py id`) that an operator pins from a trusted copy before an agent gets a workspace.

## Quick start

```bash
git clone https://github.com/scasella/core-seed && cd core-seed
bash bootstrap.sh && source .env            # Dafny 4.11, TLC, Python venv with Hypothesis/Playwright/jsonschema/cryptography
python3 gate/app_gate.py --out ../evidence-001
# -> ring 0 passes (the core is proven); ring 1 refuses with instructions. That refusal is where an agent starts.
```

Give an agent the repository and this instruction:

> Read AGENT.md and do what it says. You are done when `python3 gate/app_gate.py --out <fresh dir>` reports
> `behavioral_assurance=passed` and `application_delivery=passed`, with `human_approval=pending`. Do not edit
> anything the gate calls frozen.

When it reports done, judge it yourself with the **pristine** release's gate, pinned:

```bash
RELEASE="$(python3 gate/release.py id)"                      # capture from your trusted copy, keep it out of the agent's reach
python3 gate/app_gate.py --candidate /path/to/agent-checkout --expected-release "$RELEASE" --out ../evidence-002
```

`app-claims.json` in the evidence directory carries three separate statuses and a `release_ready` flag that
needs all of them, an authoritative pinned run, a sandboxed browser, and an Ed25519 review attestation
(`gate/review.py`) that only an operator can produce.

To see a conforming build without an agent: `validation/judge_example.sh examples/build-a ../evidence-ex-a`.

## What a green result means, and does not

`behavioral_assurance=passed` means: the core's obligations are proved (Dafny, include closure verified,
translation reproduced byte-for-byte); the agent's design model is model-checked within configured bounds
and provably not vacuous for the behaviours the coverage obligations name; the running service is not
falsified by the frozen black-box harnesses (domain validation, idempotency, conflicts, crash-and-restart,
event contract, concurrency, agreement with the proven core under bursts, generated monitor silent).
`application_delivery=passed` means the required workflows ran in a real browser at two viewports.
`human_approval` is read only from a signed attestation.

It does not mean the application is correct. Conformance of the implementation to the design model is by
test; the proof's runtime assumptions are established by validation code, not by the compiler; the monitor
sees only emitted events; a process boundary is not a sandbox. `kernel/tcb.yaml`, `INTENT.md` and
`CUSTOMIZATION.md` say where the lines are.

## Documents

- `AGENT.md` — the contract for the agent
- `INTENT.md` — what the core means, what it excludes, how behaviour is legitimately changed
- `CUSTOMIZATION.md` — presentation vs. supported profiles vs. behavioural extensions
- `ARCHITECTURE.md` — the rings and why the judge is shaped the way it is
- `docs/VALIDATION.md` — every gate run behind this release, including the reviewers' bypass candidates being refused
- `docs/FRONTIER.md` — the research this is built on (vericoding benchmarks, specification gaming, evaluator isolation)
- `docs/hybrid-spec-reference.html` — the hybrid spec-driven development essay this project started from

## Contributing and security

See `CONTRIBUTING.md`. Changes to frozen directories are a new release (`gate/release.py seal`), and every
release must re-run `docs/VALIDATION.md`'s matrix. Report evaluator bypasses privately per `SECURITY.md`;
they are the most valuable contribution this project can receive.

## License

MIT. See `LICENSE`.
