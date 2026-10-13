# RFC 0003 — Self-service adoption: agent feedback, authoring, existing projects

| | |
|---|---|
| Status | Implemented in v0.9.0 (roadmap milestone M4). § 8 says which M4 exit criteria are met and which are not. |
| Applies to | `gate/` (the evaluator), every pack's `pack.yaml`, `templates/pack/`, `integrations/`, `validation/` |
| Builds on | RFC 0001 (packs and evidence), RFC 0002 (four packs, one evaluator). Nothing in their formats is withdrawn. |

## 1. What M4 asked

Three journeys, each cheap enough that nobody has to reconstruct a project with a maintainer's help:

- **The application builder** picks a seed, gives an agent a workspace and gets failures it can act on. For small
  models: a compact task packet (the relevant contract ids, what may be edited, the first failing obligation, a minimal
  counterexample, the rerun command), and the failure's kind stated, not left to be inferred from a log.
- **The contract author** gets a scaffold, consistency and adequacy checks, and a release review that is not their own.
  Parameters have defined domains and evidence; configuration does not silently inherit a proof.
- **The existing-project adopter** protects one workflow in an existing codebase, incrementally, and reports say what
  is covered and that nothing else is.

Plus: a stable command-line and machine-readable interface that other tools (GitHub Spec Kit, CI, agent harnesses)
call through thin wrappers.

## 2. Failure categories

Every failed check now carries `category` and `category_basis` in `evidence.json` (and `category` in
`app-claims.json:checks`). The six categories are the roadmap's:

| Category | Meaning | Typical source |
|---|---|---|
| `violation` | the implementation violates the contract | a harness assertion, a model-check counterexample, a delivery obligation that failed |
| `not_exercised` | the required behaviour was not exercised | a coverage obligation the design never reaches; a delivery probe that never reached its precondition |
| `evidence_missing` | something the evaluation needs is absent | a required file (`files_present`), an incomplete SPEC |
| `toolchain_unavailable` | a declared tool is missing | the check's `tools` recorded as unavailable; exit 126/127; "Unable to access jarfile"; an unavailable browser |
| `contract_change` | only a new release could make this pass | an edited frozen file, a manifest key or value the pack does not allow |
| `infrastructure` | the evaluator, the release or the machine failed | an exception or timeout inside a check; the pack's own oracle failing (`about: release`); seal or pin mismatch |

How a category is decided (`gate/packet.py classify`), first match wins: an exception or timeout in the evaluator;
a declared tool recorded as unavailable, or tool-missing output; the pack's `failure_category` for the check; the
check being `about: release`; what the kind or the delivery adapter reported; the kind's default. The basis is
always recorded, because the category is an inference and a reader should be able to disagree with it.

Two consequences for the evaluator, both fail-closed:

- An exception or timeout inside a check used to end the run with a traceback and no evidence. It is now a refusal
  in category `infrastructure`, with evidence and a packet.
- A toolchain entry whose version command fails is recorded as `unavailable` (it used to record the error text as
  the version). Available tools are recorded exactly as before, so evidence keys do not change for them.

Pack-side declarations (all optional, validated by `gate/pack.py`):

```yaml
- id: design.coverage
  failure_category: not_exercised      # an unreached behaviour was not judged, not violated
- id: kernel
  about: release                       # the pack's own oracle: a failure is the release's, not the candidate's
```

A delivery adapter may return `failure_category` and `failing` (the obligation ids it found failing); all three
adapters do. Harness tests name the contract records they bear on in their docstrings (`"""Contract: A3."""`), so the
packet can name the record a failing test is about rather than every record the check verifies.

## 3. The task packet

After every run the evaluator writes `task-packet.json` (format `pith.task-packet/v1`, schema
`gate/schemas/task-packet.schema.json`) and `TASK.md` (the same content to read) next to `app-claims.json`, and prints
the path. It is a few KB: the largest in the validation runs is under 6 KB.

| Field | Content |
|---|---|
| `state` | `done`, `refused` (a blocking check failed) or `failing` (a non-blocking one did) |
| `statuses`, `done_when` | the pack's statuses and what "done" means for it |
| `first_failure` | the check, its category and basis, the contract records it bears on (`contracts_basis` says whether the failing output named them or they are every record the check verifies), a minimal counterexample, the tail of the output, and what to do next for that category |
| `other_failures`, `not_yours` | later failures; what is pending but not the candidate's to produce (human approval, enforced isolation, a contained browser) |
| `editable`, `frozen` | the agent-owned dirs (plus `include` paths), the manifest keys allowed; everything frozen |
| `rerun` | the exact full rerun with `--reuse` of this run, a focused rerun of the failing test where there is one, and `evidence.py impact` |
| `coverage` | what the evidence covers (§ 6) |

The counterexample comes from the tool that found it and is labelled so: Hypothesis's shrunk falsifying example,
TLC's trace (breadth-first, so shortest), the failing pytest test up to its failing line with the assertion, or the
tool's error lines. Domain-free: it is about tools, not about any pack.

`python3 gate/packet.py EVIDENCE` or `python3 gate/cli.py packet EVIDENCE [--json]` prints a run's packet again.

## 4. The command-line interface

`gate/cli.py` (and the `./pith` wrapper in a source checkout) is the one entry point for people, agents and wrappers.
With `--json` every subcommand prints exactly one JSON document on stdout; exit codes are 0 ok, 1 refused or not ok,
2 completion status not reached, 3 usage.

| Command | What it does |
|---|---|
| `doctor [--pack DIR]` | is this machine ready for the pack: Python, the release seal, each declared tool and toolchain entry, candidate runtimes, whether a browser launches. Says how to fix each missing item. |
| `verify -- <app_gate arguments>` | judge, then print the packet (`--json`: the packet as JSON on stdout, the judge's log on stderr) |
| `packet EVIDENCE` | an earlier run's packet |
| `pack new NAME --out DIR` | scaffold a draft pack from `templates/pack` (§ 5) |
| `pack check DIR [--release ...]` | consistency and adequacy checks; with `--release`, an independent signed review is required (§ 5) |
| `adopt --release DIR --project DIR --subsystem TEXT --include PATH` | prepare an existing project (§ 6) |

## 5. The contract author's workflow

1. `python3 gate/cli.py pack new NAME --out packs/NAME` copies `templates/pack`: a complete, judgeable draft pack with a
   small example contract (a bounded tally with idempotent requests): `INTENT.md`, a TLA+ model and a known-wrong
   design, a black-box harness on `gate/service.py`, one conforming service and one known-wrong one with
   `expected.yaml`. CI scaffolds it, seals it, judges both examples and requires the wrong one to be refused for its
   defect with the right packet, so the template cannot rot.
2. The author replaces the example with their contract and runs `python3 gate/cli.py pack check packs/NAME`. Errors
   make a pack unfit to judge with: a record without intent, semantics, change route or a verifying check; a
   semantics file or wrong example that does not exist; no known-wrong applications or an `expected.yaml` naming a
   check that does not exist; a manifest key without a defined domain and evidence (`parameters:`, below); no
   maintainers. Warnings are what a reviewer will ask about: a behavioral record no wrong candidate exercises, a record
   `INTENT.md` never mentions, a check without `inputs`, one conforming example, no `domain_vocabulary`.
3. **Parameters.** Every manifest key a pack allows is either a `manifest_choice` (an enumerated value with its own
   checks) or declared under `parameters:` with its `domain` and the `evidence` that covers it (possibly "none: report
   label"). A key with neither is an error: a value outside what was checked must not inherit the checks' evidence.
4. **Release review.** `pack check --release --reviewer-key PUB` additionally requires a valid review of *this
   release digest*, signed with `gate/review.py sign-pack` by someone who is not one of the pack's maintainers,
   covering intent, traces and wrong candidates. Reviews live in `packs/NAME/reviews/`, outside the policy dirs, so
   they are not part of the digest they sign; any change to the pack invalidates them. The stage `pack check` prints is
   derived, not declared: `unfit`, `draft (fit to judge with; not independently reviewed)`, or `released`.

None of the three shipped packs has an independent review yet (§ 8), so all three report `draft`.

## 6. Existing projects

A pack that allows the manifest keys `include` and `subsystem` (all three now do) can be adopted by an existing
project for one workflow:

```yaml
# app.manifest.yaml in the existing project's root
name: Handbook reviews
runtime: python
include: [handbook]                     # the project's code the pack's entrypoints use
subsystem: review of policy documents (handbook/reviews.py), through service/ and cli/
```

The evaluator copies the included paths into the judged artifact with the agent-owned dirs and digests them; an
included path must be relative, inside the candidate, without `..`, and not a policy dir, `gate/` or an
evaluator-owned path (`policy · included paths`, category `contract_change`). Nothing else of the project is copied.
Every run now reports `coverage` in `app-claims.json` and the packet: the subsystem, the included paths, the judged
paths, and the statement that evidence covers only the pack's contract records as exposed through the entrypoints and
that nothing else in the repository is covered.

`gate/cli.py adopt` writes the manifest and `PITH.md` (an adoption record: the operation, the protected behaviour,
the checks, and a table of what each refusal led to), never copies the release into the project, never overwrites,
names the entrypoints still to write, and refuses a project whose code lives in a directory named like one of the
pack's policy dirs (the judged workspace would hold the pack's copy there instead).

The worked example is `packs/approval/examples/adopt-handbook`: a small handbook application (pages, search, a site,
and a review workflow) that adopts `pith.approval` for its review workflow only, with two thin entrypoints over its
own `handbook/reviews.py`. Its record shows the adoption finding a real defect (approvals of an earlier revision
counted toward the quorum), kept as the known-wrong fixture `adopt-handbook-stale`. Guide: `docs/ADOPTING.md`.

## 7. Thin integrations

`integrations/spec-kit/` adds a verification step to a GitHub Spec Kit workflow: one command file that runs
`gate/cli.py verify --json`, acts on the packet, and never edits frozen files or the acceptance policy. It replaces
nothing in Spec Kit's specify/plan/tasks/implement flow. The pattern for any other agent or tool is the same: call the
CLI, read the packet.

## 8. M4 exit criteria

| Criterion | State |
|---|---|
| Actionable failures for agents, small ones included: compact packet, six categories | **Met.** Every known-wrong application of the three packs written here (12), and since M3 was merged in the six of the outside author's quota pack, gets the expected category and names the expected contract records (`validation/judge_wrong.py`); one run per category on the reservation pack (`validation/packets.py`); schema-valid packets under 6 KB. |
| Contract-author scaffold, consistency and adequacy checks, separate release review | **Built.** `pack new`, `pack check`, `review.py sign-pack`; the scaffold is judged in CI. No pack has been through an independent review yet. |
| Existing-project support, coverage stated | **Built and demonstrated in the repository.** `include`/`subsystem`, `coverage`, `adopt`, the handbook example, `validation/adoption.py`. |
| Stable CLI and machine-readable protocol; thin wrappers | **Built.** `gate/cli.py`, `integrations/spec-kit/`. |
| **Exit gate:** external developers complete a fresh-seed build and an existing-project adoption using published instructions, with setup failures and interventions recorded | **Not met.** It needs developers outside the project. What it depends on exists: the instructions (`README.md`, `AGENT.md`, `docs/ADOPTING.md`), `doctor`, the packet, and the trial record format (`docs/ADOPTING.md` § Recording a trial; `validation/adoption.py` writes one for its scripted run). The scripted runs are not external adoption and are not counted as such. |

## 9. Limits

- Categories are inferred from what the tools say. A candidate service that hangs is reported as `infrastructure`
  (a timeout) with a basis saying the cause may be the candidate's; a candidate whose own code raises
  `ModuleNotFoundError` inside its service shows as a violation (the service did not start), not as a missing tool.
- The packet names contract records through the tests' docstrings; a harness whose tests carry none falls back to
  every record the check verifies, and says so.
- The focused rerun assumes a checkout that holds the release (a seed checkout does; an adopting project does not,
  and gets only the full rerun).
- `pack check` checks references and structure, not meaning: whether `intent` matches `semantics` is the reviewer's
  work, which is why the release review exists.
- `include` copies code the entrypoints use; it does not establish that the entrypoints are the only way that code is
  reached in production. The coverage statement says what was judged, not how the project is deployed (M5 binds
  evidence to deployment).
