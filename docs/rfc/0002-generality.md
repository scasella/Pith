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
| Wrong candidates | 2 wrong applications + a 19-case matrix | 8 wrong cores + 4 wrong applications | 8 wrong designs + 3 wrong applications |
| Accepting/rejecting traces | `obligations/design` coverage, kernel adequacy | `spec/traces.dfy` T1–T11 | `model/traces.yaml` T1–T11 |

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
scans `gate/` for the vocabulary, contract ids and check ids of every pack.

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
| `tlc` `expect: {violated: X}` also accepts an action property | approval (after the trace review) | known-wrong designs that break a temporal property (`PublishedIsFinal`, `PublishOnlyApproved`, `RevisionsGrow`, `ApprovalsGrow`) could only be shown to break some invariant instead |
| a blocking failure refuses the status its check contributes to | approval | only `refusal_status` could read `refused`, so a failing model check would have been reported against `behavioral_assurance` |

What needed **no** change: the `tlc` kind (the approval pack's model, adequacy designs and refinement all use it
or `command`), `adapter` (a CLI adapter returns the same shape as a browser adapter), `attestation` (the approval
pack simply has none), `all_pass`/`from_check` statuses, contract records, evidence keys, invalidation and reuse,
the in-toto statement, the frozen-file and seal checks, the isolation probe.

**The fourth pack, by an outside author, needed none.** `packs/quota/` (sliding-window quotas delivered as a
library, Python or Node.js, with no service) was written by a separate agent from the docs and the existing packs,
starting from the M3 tree, with no edits to `gate/`, `validation/` or any other pack. Its friction log is
`packs/quota/AUTHORING-NOTES.md`. It wanted five additions and worked around each inside the pack; none is a
rewrite, and they are the open list for the evaluator:

| Wanted | Workaround in the pack |
|---|---|
| a `Supervised` mode for a long-lived driver on stdin/stdout with line readiness | one short `run_as_candidate_full` process per program (about 50 ms each) |
| `stdin` for `run_as_candidate_full` | input as a JSON argument; state handed from one consumer's stdout to the next one's arguments |
| a helper for a directory the candidate may write, outside `Supervised` | the same stdout-to-argument hand-over, rather than copying the `chown` logic into the pack |
| a way to say *why* a command must fail (`expect_exit: nonzero` accepts a type error) | `harness/adequacy.py`: only postconditions may fail, one per claimed obligation, and the wrong core must differ on its named trace |
| `source_rules` over a glob | determinism tested behaviourally instead of by source scan |

Its documentation gaps (no guidance for a pack without a service; the judge's user, environment and timeout for
harness commands; `judge_wrong.py` hardcoding the status names `behavioral_assurance` and `application_delivery`
and dropping pytest parameters; `domain_free.py` false positives; `INTENT.md` not frozen) are answered in
`docs/PACK-AUTHORING.md` § 4 where they are documentation, and left open where they are code.

The reservation pack is judged with the same scoped results as the v0.6.0 judge after these changes
(`validation/compare_m1.py`, CI).

## 5. How the approval pack holds a service to a TLA+ spec

The booking pack can test the service against its verified core because the core is executable (a translation).
A TLA+ spec is not. The approval pack bridges the gap in two steps, both checked on every run:

1. `harness/reference.py` writes the same transition system as a Python function, adding only what the service
   contract needs and the model does not (unbounded revisions, the reason for a refusal).
   `harness/refines.py` runs TLC with `-dump dot,actionlabels`, rebuilds the complete reachable graph of the
   reference from the same constants, and requires the same initial states, the same 1898 reachable states and the
   same 2330 labelled transitions. Every state carries the model's history variable `last` (who did the step), so
   a reference that lets the wrong actor act fails it, as does a one-line mutation of the reference.
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
| Three structurally different domains on the same evaluator | **Met.** `validation/generality.py`: one evaluator digest over runs of all four packs; CI job `packs`. |
| Application variation | **Met** in both new packs (§ 6). |
| Implementation variation with its own evidence | **Met**: booking's Node.js profile on the JavaScript translation, booking's custom store, approval's two stacks (§ 6). |
| Formalization review: authors review accepting and rejecting traces before sealing | **Met by an independent agent reviewer; no human review yet.** `packs/booking/spec/traces.dfy` and `packs/approval/model/traces.yaml` run on every judge (`core.traces`, `model.traces`). A separate agent that had not written the packs reviewed every trace against INTENT.md alone, derived each outcome by hand, and wrote mutants the traces should catch: `docs/reviews/m3-trace-review.md`. Both packs came back "accept with changes"; all 15 findings were applied (new traces T9–T11 in both packs, a history variable `last` in the approval model so actors are compared, four more invariants, an action property, five more wrong designs, two more wrong cores, one-minute nudges in booking conformance), and every reviewer mutant is now caught. The reviewer is an agent, not the pack's human owner; a human sign-off is still the release condition. `python3 packs/approval/harness/traces.py --markdown` prints the approval traces for review. |
| Independent authorship: a pack written by someone other than the principal maintainer, without editing the evaluator | **Met by an independent agent author; no human author yet.** `packs/quota/` was written from the docs by a separate agent, with no edits to `gate/`; it seals, both examples reach every status, all six wrong applications are refused for exactly their defect, and its runs share the evaluator digest of the other packs (`validation/generality.py`, CI). It reported five wanted additions and no needed rewrite (§ 4). The author is an agent working in the maintainer's environment, not an outside person. |

The roadmap's exit gate ("independent authors identify no need to rewrite its internals") is passed for an
independent agent: the quota author changed nothing in `gate/` and listed additions, not rewrites (§ 4). It is not
yet passed for a human: neither the traces nor a pack have been reviewed or written by a person other than the
maintainer, and that remains the condition for calling the packs release-ready.

## 8. Limits

- The isolation container (`gate/isolation/Containerfile`) has no Node.js; the enforced-isolation CI run is still
  the reservation pack's `build-a`. The new packs run as the candidate's user where `SEED_CANDIDATE_UID` is set,
  and advisory otherwise.
- The approval actor model is simulated: who an actor is, is given. Authentication is out of the contract.
- The approval reference equals the spec only within 4 actors, quorum 2 and 3 revisions.
- Evidence reuse across packs is not attempted (records are release-bound, RFC 0001 § 6).
- Packs do not compose: an application using bookings and approvals together has no joint contract (M5).
