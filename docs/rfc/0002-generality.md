# RFC 0002 — Three packs, one evaluator

| | |
|---|---|
| Status | Implemented in v0.8.0 (roadmap milestone M3). § 7 says which M3 exit criteria are met and which are not. |
| Applies to | `gate/` (the evaluator), `packs/booking/`, `packs/approval/`, `validation/` |
| Builds on | RFC 0001 (contract packs and evidence). Nothing in RFC 0001's formats is withdrawn. |

## 1. What M3 asked

The roadmap's M3 is: three structurally different domains judged by the same evaluator, written by authors who
find no need to rewrite its internals; application variation (different interfaces or workflows on one
contract) and implementation variation (a materially different service stack carrying its own implementation
evidence); and explicit formalization review through concrete accepting and rejecting traces before a pack is
sealed. Where the abstraction does not fit, revise it before adding more packs.

This RFC records what the two new packs needed from the evaluator, what was changed for them, and what stayed
the same.

## 2. The three packs

| | `pith.reservation` (root) | `pith.booking` (`packs/booking/`) | `pith.approval` (`packs/approval/`) |
|---|---|---|---|
| Domain | holds against a credit limit, capture | half-open intervals on resources, cancel, atomic reschedule | documents, roles, revisions, two-approver quorum |
| New difficulty | (baseline) | time intervals, boundary convention, independent resources | actor identity (simulated), permissions, revisions, stale approvals |
| Oracle | Dafny kernels + TLA+ core actions the candidate's design must extend | a Dafny spec with a verified core (`spec/BookingCore.dfy`, 13 obligations) | a TLA+ state machine (`model/Approval.tla`), no core |
| What the candidate writes | a TLA+ design, the service, the page | the service (on a shipped profile, or a custom one) and the page | the whole workflow (service and CLI), no shipped core |
| How the service is judged | black-box against the proven kernel | black-box against the verified core (Python translation) | black-box against a reference model shown equal to the spec within bounds |
| Backend stacks shipped or shown | Python + SQLite profile | Python + SQLite profile; Node.js + journal profile on the JavaScript translation; a custom Python store | Python + SQLite; Node.js + journal (both written by the candidate) |
| Delivery | browser page (W1–W6, I1–I6) | browser page (BW1–BW6, BI1–BI3) | command-line client (AW1–AW5, AI1–AI3), no browser |
| Human evaluation | yes (E1–E3) | yes (BE1–BE2) | none |
| Statuses | behavioral_assurance, application_delivery, human_approval | the same three | model_assurance, behavioral_assurance, application_delivery |
| Wrong candidates | 2 wrong applications + a 19-case matrix | 6 wrong cores + 4 wrong applications | 3 wrong designs + 3 wrong applications |
| Accepting/rejecting traces | `obligations/design` coverage, kernel adequacy | `spec/traces.dfy` T1–T8 | `model/traces.yaml` T1–T8 |

The approval pack differs from the other two on every axis the evaluator could have quietly depended on: no
Dafny, no core shipped to the candidate, a different oracle language driving the service conformance, no
browser, no attestation, a fourth status, and a different `area` vocabulary (`model`, `service`, `delivery`).

## 3. Layout: one evaluator, several packs

RFC 0001 § 9 left open whether a release carries one pack or several. M3 keeps **one pack per release** and puts
several releases in one repository:

- the repository root stays the reservation pack (`pack.yaml`, its policy dirs, `gate/frozen.sha256`,
  `release.seal.json`), so nothing an operator already pins moves;
- every other pack is a directory `packs/<name>/` with its own `pack.yaml`, policy dirs, `frozen.sha256` and
  `release.seal.json`;
- `python3 gate/release.py build --pack packs/<name> --out DIR` lays that pack next to a copy of `gate/` (its
  frozen list becomes `gate/frozen.sha256` there), and the result has the same release digest as
  `release.py id --pack packs/<name>` (CI checks both). A judge runs from the built release exactly as from the
  root; `validation/judge_example.sh --pack` does this for every run.

So the pin still identifies the pack, a booking release cannot be passed off as an approval release, and the
evaluator code is the same bytes in all three: `evidence.json:evaluator_digest` (the digest of `gate/` without
the frozen list it carries) is identical in every run, which `validation/generality.py` checks.

## 4. What the new packs needed from the evaluator

Every change is listed with the pack need that forced it. None names a domain: `validation/domain_free.py` now
scans `gate/` for the vocabulary, contract ids and check ids of all three packs.

| Change | Needed by | Why the existing evaluator did not fit |
|---|---|---|
| `release.py build/id/seal --pack` | both | one pack per release (§ 3) |
| `each: {glob: PATTERN}` | booking (`core.adequacy` over `spec/wrong/*.dfy`) | `each` only read a list file; a list of wrong cores beside the cores is a second place to forget one |
| `expect_exit: nonzero` on `command` | booking (a wrong core must fail to verify) | the reservation pack's adequacy suite lived inside its own kernel gate script; a pack using `dafny verify` directly had no way to say "this must be rejected" |
| `{item}` in `command`, `why` | booking | the expanded item was only available to `tlc` |
| `gate/service.py` (`Supervised`: start the candidate's service as the candidate's user, readiness, SIGKILL, restart on the same state, `{port}`/`{state}`) | both | the reservation pack's supervisor did this for one fixed entrypoint inside the pack; two more packs would have been two more copies of security-relevant code |
| `sandbox.limits(overrides)`, `run_as_candidate_full` | booking and approval Node stacks; approval CLI | V8 reserves address space for WebAssembly, so the fixed `RLIMIT_AS` killed Node at start-up (memory is then bounded by the isolation profile's cgroup); a CLI's verdict needs its exit code, stdout and stderr separately |
| `gate/browser.py` (launch options, browser user, containment) | booking | the containment condition lived in the reservation adapter; the booking adapter needed the same rule, and a rule about the judge's own browser is the evaluator's |
| isolation scope names `candidate.runtimes` | booking, approval | the scope text said the candidate runs on "the judge's pinned Python"; Node is now a candidate runtime |
| exit code from `ready(completion_status)` | approval | the judge compared the completion status to the literal `"passed"` instead of the pack's own `ready` condition |
| a blocking failure refuses the status its check contributes to | approval | only `refusal_status` could read `refused`, so a failing model check would have been reported against `behavioral_assurance` |

What needed **no** change: the `tlc` kind (the approval pack's model, adequacy designs and refinement all use it
or `command`), `adapter` (a CLI adapter returns the same shape as a browser adapter), `attestation` (the approval
pack simply has none), `all_pass`/`from_check` statuses, contract records, evidence keys, invalidation and reuse,
the in-toto statement, the frozen-file and seal checks, the isolation probe.

The reservation pack is judged with the same scoped results as the v0.6.0 judge after these changes
(`validation/compare_m1.py`, CI).

## 5. How the approval pack holds a service to a TLA+ spec

The booking pack can test the service against its verified core because the core is executable (a translation).
A TLA+ spec is not. The approval pack bridges the gap in two steps, both checked on every run:

1. `harness/reference.py` writes the same transition system as a Python function, adding only what the service
   contract needs and the model does not (unbounded revisions, the reason for a refusal).
   `harness/refines.py` runs TLC with `-dump dot,actionlabels`, rebuilds the complete reachable graph of the
   reference from the same constants, and requires the same initial states, the same 1314 reachable states and the
   same 1602 labelled transitions. A one-line mutation of the reference fails it.
2. `harness/conformance.py` (Hypothesis) drives the running service and the reference with the same generated
   commands by every actor, and requires the same outcome, reason and resulting document each time.

So the service is judged against the spec, exhaustively equal within the model's bounds, by test beyond them.
That is weaker than the booking pack's verified core and is stated as such (`model/assumptions.yaml`, the
`behavioral_assurance` text).

## 6. Variation, as built

**Application variation.** Booking: a room calendar with a timeline (`calendar-py`) and a front-desk table
(`desk-node`) and a third app on its own store (`custom-py`), all on one UI contract. Approval: two CLIs with
different human output and different request-id generation (`approvals-py`, `approvals-node`) on one CLI contract.

**Implementation variation, with its own evidence.**

- Booking, Node.js: the core is Dafny's JavaScript translation, reproduced byte-for-byte on every run
  (`translation.node`), behind a journal store with fsync-before-ack and torn-tail recovery, with its own profile
  tests (`profile.node`: atomicity across interleaved turns, durability, replays, invalid input, agreement with
  the core). This is a second backend, not a JavaScript interface on the Python backend.
- Booking, custom: the candidate's own store, judged only through the service against the verified core.
- Approval: a Python/SQLite service and a Node.js journal service with a different document representation
  (approvals held per revision), each judged by the same 30 black-box checks and the conformance property.

## 7. M3 exit criteria

| Criterion | State |
|---|---|
| Three structurally different domains on the same evaluator | **Met.** `validation/generality.py`: one evaluator digest over runs of all three packs; CI job `packs`. |
| Application variation | **Met** in both new packs (§ 6). |
| Implementation variation with its own evidence | **Met**: booking's Node.js profile on the JavaScript translation, booking's custom store, approval's two stacks (§ 6). |
| Formalization review: authors review accepting and rejecting traces before sealing | **Built, not done.** `packs/booking/spec/traces.dfy` and `packs/approval/model/traces.yaml` run on every judge (`core.traces`, `model.traces`), and each wrong design differs from the spec on a named trace. The traces were drafted by the same agent that wrote the packs; a human author has **not** yet reviewed them. Until someone does, the packs are sealed for evaluation, not for release. `python3 packs/approval/harness/traces.py --markdown` prints the approval traces for review. |
| Independent authorship: a pack written by someone other than the principal maintainer, without editing the evaluator | **Not met.** All three packs were written in the maintainer's repository by the same author. What it depends on exists: the pack format (RFC 0001), the authoring guide (`docs/PACK-AUTHORING.md`), `gate/release.py build --pack`, `judge_example.sh --pack`, `judge_wrong.py --pack`, `domain_free.py`. The test of the abstraction is an outside author doing this and reporting what they had to change. |

The roadmap's exit gate ("independent authors identify no need to rewrite its internals") is therefore not
passed. § 4 is the record of where the abstraction did not fit for this author; an independent author's list is
the evidence M3 still needs.

## 8. Limits

- The isolation container (`gate/isolation/Containerfile`) has no Node.js; the enforced-isolation CI run is still
  the reservation pack's `build-a`. The new packs run as the candidate's user where `SEED_CANDIDATE_UID` is set,
  and advisory otherwise.
- The approval actor model is simulated: who an actor is, is given. Authentication is out of the contract.
- The approval reference equals the spec only within 4 actors, quorum 2 and 3 revisions.
- Evidence reuse across packs is not attempted (records are release-bound, RFC 0001 § 6).
- Packs do not compose: an application using bookings and approvals together has no joint contract (M5).
