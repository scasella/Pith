# RFC 0007 — Autonomous assurance: runtime composition, adversarial adequacy, distilled counterexamples, deterministic interleavings, shadow oracles, fork-join handoffs

| | |
|---|---|
| Status | Implemented in v0.13.0 (roadmap milestone M7). Written as the design before implementation and corrected to what was built; § 11 records what was checked and § 12 what this does not show. |
| Applies to | `gate/compose.py`, `gate/redteam.py` (new), `gate/packet.py`, `gate/shrink.py` (new), `gate/interleave.py` (new), `gate/trace.py` (new), `gate/change.py`, `gate/evidence.py`, `gate/app_gate.py`, `gate/cli.py`, `gate/pack.py`, `gate/schemas/`; `compositions/booking-quota` (new); `profiles/sqlite-occ` (new); the booking, quota and reservation harnesses; `obligations/app/faultproxy.py`; `obligations/boundary/`; `experiments/harness.py`; `evolution/handoff/fork-join` (new); `validation/` |
| Builds on | RFC 0001–0006. No format identifier is withdrawn or changed; every format change below adds an optional field or a new identifier (`COMPATIBILITY.md`). |

## 1. What was asked, and what this RFC decided differently

Milestone 7 asks for six capabilities, each to be proved non-vacuous by a known-wrong case that fails for exactly its
reason: (1) composed packs exercised at runtime, under faults that land between the steps of a cross-component
operation, including a staggered upgrade of one component; (2) an adversarial loop that finds mutants a pack's gate
accepts although they violate its intent, and ratchets them into the pack's known-wrong suite; (3) failures distilled
into domain-level counterexamples that leak nothing of the judge; (4) concurrency defects found deterministically, and
an optimistic-concurrency storage profile; (5) the boundary monitor and verified core run as a shadow oracle beside a
live service, with divergences shrunk into regression traces; (6) handoffs between agents working in parallel, merged
with evidence reused only where it is sound.

Four places where this design does not do what the request literally says, and why:

- **Service-starting checks are never reused, including in a merge (track 6).** The request asks that a fork-join merge
  skip headless-browser workflows on untouched partitions. `ARCHITECTURE.md` and RFC 0001 make "everything that starts
  the candidate's service always runs again" a soundness rule: a merged tree is a new artifact, and only observing it
  says what it does. The merge gate proves which results are *unaffected* and reuses the cacheable ones (proofs and
  model checks); it re-runs every check that starts the service. § 8's conflicting merge is caught exactly because of
  this rule.
- **The interleaving controller is evaluator code (`gate/interleave.py`), not `obligations/service/`.** Three packs use
  it (reservation, booking, quota), and `obligations/` is only in the reservation pack's release; service supervision
  moved into `gate/` for the same reason in RFC 0002 § 4.
- **`obligations/boundary/generate.py` is not used for compositions.** It derives the reservation pack's interface from
  its kernel tags. A composition's runtime contract is hand-written policy, as the booking and approval packs' API
  schemas are. The generator is extended for the shadow oracle instead (track 5).
- **`validation/matrix.py` stays the reservation pack's mutation matrix.** "Validation runners for every new capability"
  is met the way earlier milestones registered theirs: one `validation/*.py` runner per capability, wired into
  `.github/workflows/gate.yml`, listed in the matrix's runner table (`matrix.py --runners`), plus matrix cases where a
  mutation of a reservation candidate fits (§ 10).

## 2. The invariants every track keeps

| Invariant | How it is kept |
|---|---|
| No vacuous check | Every new positive check ships with a known-wrong fixture and an `expected.yaml` entry naming the exact reason. `validation/judge_wrong.py` learns one more expectation kind, `tool:`, for negatives judged by `compose verify` and `compose stagger` (`--composition DIR`) and by `handoff merge` (`--handoff DIR`) rather than `app_gate.py`, with the same "exactly these tests, exactly these invariants" semantics; a gap the red-team ratchet promotes becomes an ordinary `expected.yaml` entry whose `promoted_from` the gap record must confirm. |
| Domain-free evaluator | Every pack- or composition-specific path, command, partition, oracle and fault is declared in `pack.yaml` or `composition.yaml`; `gate/` reads declarations and names none of them. `validation/domain_free.py` runs after every `gate/` edit and also scans the new composition's vocabulary. |
| TCB and seals | No `tcb.yaml` changes. `gate/` changes, so every pack is resealed with `gate/release.py seal` and the catalog re-pinned with `gate/catalog.py pin`; nothing is hand-edited into a seal. |
| Zero oracle leakage | Distilled packets (track 3) pass a redaction filter whose output is tested to contain no host path, no stack frame and no identifier from the pack's harness code. |

## 3. Track 1 — runtime composition (`gate/compose.py verify | stagger`, `compositions/booking-quota`)

**Shape.** A cross-component operation is only observable between its steps if the steps cross a process boundary. A
runtime composition is therefore one service per component plus a coordinator, each component behind its own
judge-owned fault proxy. `composition.yaml` (still `pith.composition/v1`) gains an optional `runtime:` block:

```yaml
runtime:
  contract: runtime/RUNTIME.md            # the component and coordinator APIs, entrypoints, recovery duty
  owned_dirs: [components, coordinator]   # the candidate's artifact (plus app.manifest.yaml)
  driver: runtime/harness.py              # policy: starts services via gate/service.py, programs faults, checks state
  support: [obligations/app/faultproxy.py]   # staged into the judged workspace at the same paths
  checks:                                 # every shared invariant must be checked by at least one runtime test
    - { test: test_..., shared: [QuotaMatchesBookings], fault: "..." }
  migrations: [{ component: booking, spec: runtime/migrations/booking-v1-to-v2.yaml }]
```

`compose verify DIR --candidate APP --out OUT` assembles a fresh workspace (the evaluator, the composition's policy
files, the declared support files and a copy of the candidate's artifact, digested whole), runs the driver as pytest,
maps failing tests to the shared invariants they check, and writes a `pith.composition-report/v1` with an added
`runtime` section (artifact digest, tests, violated shared invariants). It refuses a `runtime` block in which a shared
invariant has no runtime check. The driver starts every process with `gate/service.Supervised` (the candidate's
identity, a scrubbed environment, its own state directory), so the candidate's services never see policy files.

**The reference composition, `compositions/booking-quota`.** Three components: `booking` (owns the bookings; a
pith.booking service, so the component is additionally judged by that pack), `quota` (owns the grants; a pith.quota
library behind a small idempotent HTTP wrapper) and `coordinator` (owns the saga log and the receipts it answers with).
A reservation books first, then takes one quota unit for the resource; if quota is refused, the booking is cancelled
(compensation), so a rejected booking never burns quota. Shared invariants, checked by the driver from the components'
own state through the judge's client, never from the coordinator's self-report:

- `QuotaMatchesBookings` — at rest, a resource's active bookings and its quota grants name the same requests (no booking
  without its unit, no unit without its booking);
- `ReceiptAgrees` — a receipt says `ACCEPTED` exactly when the booking is active and its unit granted,
  `QUOTA_EXCEEDED` only when the booking was compensated and no unit granted, and `CONFLICT` only when there is no booking
  and no unit. It constrains receipts that exist: a saga that crashed before writing one is `QuotaMatchesBookings`'
  business.

Faults are deterministic, programmed per request at a proxy: kill the coordinator when its call to `quota` arrives
(after the booking committed); forward a call and drop its response; kill the coordinator on the response path; sever
the compensating cancel. After each, the coordinator is restarted and the driver waits, without any client retry, for
the components to reach rest, then checks both invariants. `obligations/app/faultproxy.py` gains wildcard paths, `sever` (close the
connection without a response, before or after forwarding) and a `hook` run when the request arrives or after the service
answered (`hook_at`), which the driver uses to kill a process at that instant; a service that dies mid-call is relayed as
a closed connection, as the client would have seen it without the proxy. A runtime component is `{id, argv, ready}`;
`argv` may name `{url:ID}`, the proxy in front of another component, which `compose.py` checks resolves. A driver using a
kill hook waits for the hook to finish, not for the client's call, which returns first.

**Model.** The same composition is stated in TLA+ (`model/`, one module per component and an integration with crash and
recovery actions) and checked by `compose check`, so the runtime and the model state the same contract.

**Known-wrong.** `examples/wrong/split-saga-leak` keeps no durable saga log, so a coordinator killed between the booking
and the quota call never completes or compensates (`QuotaMatchesBookings`); `examples/wrong/orphan-receipt-on-abort`
records `ACCEPTED` when the booking succeeds and keeps it when quota then refuses and the booking is compensated
(`ReceiptAgrees`). Each has a model twin under `wrong/` that keeps both components' local rules and breaks exactly that
invariant.

**Staggered migration.** `compose stagger DIR --component booking --old-candidate OLD --candidate NEW --out OUT`:
populate composed state with the old application (its booking component at interval-booking-core/v1) under faults;
record every component's state digest; run the new booking component's own migrate entrypoint on its store only, twice;
require every other component's state byte-identical; start the new composed application on the migrated state and run
the shared-invariant checks and receipt replays. The per-component migration is judged separately by the booking pack's
own `gate/migrate.py` (`validation/upgrades.py booking`); `stagger` adds only what one pack cannot see. Known-wrong
migrations: `touches-quota-store` (also rewrites the neighbouring quota store; refused at the untouched-state step, which
no per-pack check can see) and `drops-compensated` (deletes cancelled bookings; booking's MIG1 also refuses it, and the
composition refuses it independently through `ReceiptAgrees`).

**Limits.** One composition, two components, one coordinator. The runtime check is a test of the faults it injects,
not a proof over all crash points; the model is the bounded statement of the rest. Atomicity inside each component is
that component's pack's obligation.

## 4. Track 2 — adversarial adequacy and the ratchet (`gate/redteam.py`, `pith pack redteam`)

**Definition.** An *adequacy gap* is a mutant that the pack's gate accepts although it violates the pack's intent, shown
by a *witness*: an executable check that fails on the mutant and passes on the pack's reference. Both halves are
mechanical; the redteam tool never takes a model's word for either.

**Saboteur packet** (`gate/schemas/saboteur-packet.schema.json`, `pith.saboteur-packet/v1`): the pack, the target
(`examples` — a candidate mutant, overlaid on a reference example — or `spec` — a known-wrong design or core the
release's own checks should reject), the files, the contract records and the INTENT sentence it claims to violate, and
the witness (a probe test run against the mutant's service through the pack's own harness client, or a property the
model checker checks). An external agent writes packets; no model runs in CI.

**Verdicts.** `killed` (the gate refuses the mutant; the check that refused it is recorded), `invalid-witness` (the
witness fails on the reference), `equivalent` (the witness passes on the mutant), `survivor` (accepted by the gate,
witness fails on the mutant, passes on the reference). A survivor is an adequacy gap.

**Generation.** A small deterministic operator set produces mutants without a model: flip a comparison, shift an integer
constant by one, negate a boolean, delete a statement holding a lock, drop an `INVARIANT` line from a model
configuration. The pack declares which files each target may mutate and the commands that judge and witness them
(`pack.yaml: redteam`). A generated mutant the gate does not kill is reported `unkilled` until a witness confirms it or a
person marks it equivalent: generation finds candidates, only a witness makes a gap.

**The ratchet** (`<pack>/redteam/gaps.yaml`, `pith.redteam-gaps/v1`; the pack names the file in `redteam.gaps`). Survivors are recorded `open`. `pack check`
reports open gaps (an error with `--release`), so a pack with a known gap cannot be released. When the maintainers
tighten the harness or the model and the survivor is now killed, `pack redteam --promote` moves it into
`examples/wrong/` (or the model's `wrong/`) with an `expected.yaml` entry taken from the refusal it actually got, and
marks the gap `promoted`. A gap therefore cannot close silently: it either stays open and blocks release, or
becomes a permanent known-wrong fixture.

**Demonstration** (`validation/redteam.py`). An under-specified copy of the v0.12.0 scaffold whose model configuration
lacks `INVARIANT Bounded` and whose harness lacks the bound test: generated mutants of its reference service survive, a
saboteur packet's witness (the fourth request must be refused, INTENT's T1) confirms the gap, a spec packet (a design
that ignores the bound) survives model checking, `pack check --release` refuses the pack; adding the invariant and the
test kills both, and they are promoted and then refused for exactly their reasons by `judge_wrong.py`.

**Limits.** A gap is only as meaningful as its witness; the tool checks that the witness separates mutant from
reference, not that the witness states the intent correctly, which stays a reviewer's question (`docs/FRONTIER.md`:
validating a specification against intent without people is still open). The operators are syntactic; equivalent
mutants are expected and are labelled, not counted as gaps. The fixture's first gap is not contrived: up to v0.12.0
the scaffold `templates/pack` checked its known-wrong design against that design's own configuration rather than
against `model/MC.cfg`, so dropping an invariant from `MC.cfg` went unnoticed by its adequacy check. The scaffold now
carries the tightening in `validation/redteam/tighten`: `model.adequacy` runs every `model/wrong/*.tla` against the
invariants `MC.cfg` checks (`model/redteam_tlc.py`), and the scaffold declares a `redteam` section. `evolution/tally-v1`
and `evolution/tally-v2`, sealed demonstration releases built from the old scaffold, keep the old shape. One thing the
old `tlc` check had that this does not: it required the named invariant to be violated, while `expect_exit: nonzero`
also passes the helper's exit 3 (TLC did not run, or could not parse the design), so a known-wrong design with a
syntax error passes `model.adequacy`.

## 5. Track 3 — distilled counterexamples (`gate/packet.py`, `gate/shrink.py`, `pith packet distill`)

**Structured counterexample.** `first_failure.counterexample` (already `{source, text}`) gains optional fields: `trace`
(a list of steps, each `{step, action, args, observed}`), `expected`, `observed`, `violated` (contract record ids),
`shrunk` (`{from_steps, to_steps, against}`) and `redacted: true`. Four sources are distilled:

| Source | Read from |
|---|---|
| TLC state traces | the model checker's output: action names and variable values per state, module paths and line numbers dropped |
| Oracle discrepancies | a harness assertion carrying a `pith-counterexample:` JSON line (operations, expected and observed outcome, record); the booking and quota conformance tests and the reservation lifecycle tests emit it |
| Migration diffs | `migration-report.json`: the failing step and the verify harness's `pith-counterexample:` line |
| UI and CLI contracts | the delivery adapter's per-workflow evidence: the steps the workflow took and what it saw |

**Shrinking.** `gate/shrink.py` is delta debugging (ddmin) over a step list with a predicate, plus truncation after the
first diverging step. Inside the packet path nothing live is re-run: a trace is shrunk only against a deterministic
offline oracle the pack declares (`pack.yaml: traces.oracle`), and the result says `against: oracle`. Hypothesis and
TLC already shrink their own traces; their output is kept as found.

**Redaction.** A deny-list removes absolute paths (`/Users/`, `/home/`, `/private/`, `/var/folders/`, `/tmp/`, Windows
drives), Python frames (`File "...", line N`, `Traceback`, `*.py:N:`), Node frames (`at f (file:L:C)`), pytest's echo of
the judge's own test source, and every code-shaped identifier (snake_case, camelCase, or with a digit inside) defined in
the release's Python code (`gate/` and the policy directories, collected with `ast`) that is not on the allow-list:
contract record ids, check ids, and every word of the pack's `INTENT.md`, the documents its contract records cite and
`packet.vocabulary`. Plain words are left alone even where some module uses one as a name ("found", "rows"): they read
as prose, and masking them made counterexamples unreadable without hiding anything. `pith packet
distill EVIDENCE` writes `task-packet.distilled.json` and `TASK.distilled.md`; every run of the judge writes them too.
The original `task-packet.json` is unchanged for agents that hold the seed.

**Agent loop.** `experiments/harness.py feedback EVIDENCE` prints the distilled packet for the next turn, run records
gain an optional per-turn `feedback` digest, and the dry run's scripted agents repair from distilled packets alone.

**Proof.** `validation/test_packet.py` (unit) and `validation/packets.py` (end to end, every failure category and the
known-wrong fixtures of four packs): every distilled packet is schema-valid and contains zero host paths, zero stack
frames and zero harness identifiers, while still naming the contract records and the domain actions of the failure.

**Limits.** Redaction is a filter over text the judge produced, not information-flow control; it is tested on every
fixture the project has, not proven. A shrunk trace reproduces the situation in the oracle; whether the candidate fails
on it too is known only after a rerun.

## 6. Track 4 — deterministic interleavings and an optimistic-concurrency profile

**Controller** (`gate/interleave.py`). Threads under test run one at a time; switching happens only at schedule
points: acquiring or releasing a lock, `time.sleep`, each statement on a connection of a DB-API module the pack names
(`dbapi`; the evaluator names no database), and, where a test asks for it, each line of code under declared roots.
Locks, sleeps and those connections are replaced with cooperative versions before the code under test is imported, and
the database's write lock is modelled (taken at `BEGIN IMMEDIATE` or the first write, released when the connection leaves
its transaction), so a correct store never blocks outside the controller's view. Exploration is systematic and
preemption-bounded (every schedule with at most k preemptions; iterative context bounding): the set of schedules is
fixed by the code, so a defect reachable within the bound is found on every run, with no sleeps and no timing. A step
that blocks where the controller cannot see it is reported `inconclusive` after a watchdog, never as a pass.

Where it runs, each by the judge, before candidate code:

| Where | How | Bound, points |
|---|---|---|
| quota (Python libraries) | the pack's driver, which already runs as the candidate and imports its library, gains an `--interleave` mode | 1; every line of the library |
| booking and reservation (Python services) | the service is started through `gate/interleave.py serve -- service/run.py ...`; episodes are armed through a judge-created control directory and requests are issued one at a time until each is parked | 1; locks, sleeps, statements |
| `profiles/sqlite`, `profiles/sqlite_occ` | in-process profile tests | 2; locks, sleeps, statements |

Service tests take no line points: on the reservation fixture they turned 10 schedules into 140 and a second into
fifteen. The price is stated in each test: a store whose race involves no lock, sleep or statement has only its two
serial schedules, and the test refuses that as inconclusive (it requires more than two) rather than passing it. Node.js
candidates run single-threaded JavaScript and keep the existing tests; the tests skip with that reason, and the runner
checks they skip rather than pass. The controller is judge code inside the candidate's process: a candidate can detect or
sabotage it, which can only weaken the new test, never the existing ones.

**OCC profile** (`profiles/sqlite-occ`, a new choice for the reservation pack's `profile` key). Each account row carries
a version; an operation reads the state and its version without a write lock, computes the decision with the verified
core, and commits with `UPDATE ... WHERE id = ? AND version = ?` inside one short write transaction that also re-checks
the receipt for the request id and appends the events. A failed compare-and-swap retries within a bounded budget
(100 attempts: each lost round is another operation's commit, so a burst of up to 100 operations on one account cannot
exhaust it; exhaustion changes nothing and says so). The `Atomicity` record's wording now covers both profiles (a
decision is computed from the availability current when it commits); its obligation, and so its version, is unchanged.
The profile tests explore schedules of two and three concurrent operations and check every outcome, the final account
and the exact event sequence against some sequential order through the pack's oracle (linearizability within the bound),
plus a 600-operation differential run against `profiles/sqlite`. The reservation pack gains `examples/build-occ` (build-a
on the new profile) and a known-wrong application, `examples/wrong/split-decision` (build-b whose adapter decides
outside its lock), which the deterministic test refuses on every run and the existing burst test never caught in five.

**Proof** (`validation/interleavings.py`). Run five times, each must give the identical failing set and the identical
first violating schedule: booking `check-then-insert`, quota `unlocked`, and three known-wrong OCC stores (`blind-write`,
`receipt-outside-cas`, `unversioned-read`). `expected.yaml` for `check-then-insert` and `unlocked` then names the
deterministic test as required. `retry-not-released` is not a race (it is a receipt defect after a lost response); it
is in the runner as a control showing the receipt test was already deterministic.

**Limits.** Exhaustive only within the preemption bound and for the operations a test issues; Python services and
libraries only; C extensions other than SQLite are outside the model.

## 7. Track 5 — shadow oracle and trace harvesting (`obligations/boundary`, `gate/trace.py`, `pith trace`)

**Shadow mode.** The generated monitor gains a `Shadow` class (`monitor.template.py`; regenerated into every
candidate's `gen/out/monitor.py`, which `gen.current` already diffs): it feeds events to the monitor and, at each
`op.committed`, rebuilds the operation in the pack's oracle vocabulary and replays it through the oracle
(`obligations/boundary/oracle.py`, which decides with the compiled verified core), comparing the answer the stream
records. It runs as a sidecar process that tails the service's event feed (`python3 gen/out/monitor.py shadow --events
URL --out LOG`), so it cannot crash or block the host; an in-process variant (`attach(emit)`) enqueues on a bounded queue
drained by a daemon thread and counts what it drops; the host's own emit runs first and its own exceptions are the
host's, while nothing the shadow adds ever raises into it. Without the oracle the shadow says it is monitor-only. A
divergence is one `pith.divergence/v1` line: the alert, the records it bears on, the operations so far and where they
diverged.

**Harvest.** `pith trace harvest LOG --pack DIR --out OUT` takes the first record at which the oracle disagrees with an
answer the service gave (a record whose only symptom is in the stream itself, a broken chain or a disputed state, has no
answer to disagree with and is reported, not harvested), shrinks its operations with `gate/shrink.py` against the
oracle, and writes `trace.yaml` (`pith.trace/v1`: each step with the answer the contract requires), the pack's
rendering (`traces.render`; for the reservation pack a Dafny `{:test}` method in the form of `kernel/adequacy/traces.dfy`,
meant to be added at `traces.render_dir`), `traces.provenance.yaml` (unsigned: source digest, shrink statistics) and
`revocation.draft.yaml` (a `pith.revocations/v1` release entry, explicitly a draft: it applies only if `gate/deploy.py
check` shows the deployment was the accepted artifact; otherwise the deployment ran something the evidence never
covered and nothing is revoked). `pith trace replay TRACE --candidate APP` runs a trace against a service through the
pack's replay harness. A shrunk trace can fail earlier than where it was harvested, since its history is shorter; the
replay says where.

**Proof** (`obligations/boundary/test_monitor.py`, `validation/shadow.py`). Unit: the shadow records an anomalous
transition and a disputed state without raising, survives a failing listener, counts overflow, and a good stream yields
nothing. End to end, on the club desk: a copy whose own service code carries a production drift (once an account holds
three live holds, the availability it reports ignores the newest one; the core still decides on the true state, so
decisions, holds and views are unchanged and the drift is invisible in ordinary use). The drift is in the candidate's
code because `profiles/` is release policy, which a judge or a replay always takes from the release. The sidecar finds
nothing on the accepted desk and a divergence on the drifted one; harvest shrinks 15 operations to 6; the rendered test
passes `dafny test` against the verified core (and fails with the observed figure in place of the required one); replay
fails on the drifted desk and passes on the accepted one; the revocation draft is not to be filed, because the drifted
artifact is not the accepted one.

**Limits.** The shadow sees only what the service emits (RFC 0004 § 5); a side effect that bypasses the events is
invisible. A revocation is a draft until a person files it.

## 8. Track 6 — fork-join handoffs (`gate/change.py merge`, `pith handoff merge`)

**Partitions.** A pack declares them (`pack.yaml: partitions`, first match wins; `boundary: true` marks an interface
partition). The reservation pack: `migration` (`service/migrate.py`), `design` (`design/**`), `integration`
(`adapter/**`, `service/**`, `app.manifest.yaml`), `presentation` (`ui/**`, `app/**`), and the boundary `interface`
(`gen/**`). The frozen interface documents (`UI-CONTRACT.md`, the generator's inputs) are release content and cannot
change in any branch.

**Merge.** `change.py merge --base-candidate DIR --base EVIDENCE --branch NAME=DIR[:EVIDENCE] ... --out MERGED [--judge
EVIDENCE_OUT]` refuses when the base candidate is not the artifact the base evidence judged; computes each branch's
changed paths; refuses on a textual conflict, two branches touching one partition, or any branch touching a boundary
partition; writes the merged tree; computes per-partition digests (the compositional seal); recomputes evidence keys on
the merged tree (`evidence.current`) and reports, for every check, whether its key matches a record in the base or a
branch's evidence (`holds`, with the source) or must re-run, and which branch records rest on a partition another branch
changed. With `--judge` it runs the judge on the merged tree with every evidence directory offered: `app_gate.py --reuse`
may now be given more than once, and a cacheable record is reused from any of them whose release, evaluator and key
match. The merge is accepted only when that judge run is. Report: `pith.merge-report/v1`, `authoritative: false` like
every change report; the judge decides.

**Recorded scenario** (`evolution/handoff/fork-join`, scripted like RFC 0004 § 7's handoff, not model agents). From the
accepted `examples/build-a`: branch `agent-a` swaps the storage profile to `sqlite-occ` (the files in which
`examples/build-occ` differs: the manifest and the service, so the `integration` and `migration` partitions), branch
`agent-b` overhauls the page and reads the authorization amount bounds from the service's `/openapi.yaml`
(`presentation`), branch `agent-c` trims the service of the `/openapi.yaml` route, which nothing in the judge fetches
(`integration`). Each is accepted alone, with the base's evidence offered. `a+b` merges: no conflict, the judge on the
merged tree is accepted reusing exactly the ten cacheable results (the kernel proof and every TLC check) and running the
service checks and the browser again; seven branch results that read another branch's partition are listed and none is
reused. `b+c` has disjoint partitions and no static conflict, and the cacheable evidence holds, but the judge on the
merged tree refuses at delivery (every action on the page stays disabled: I1 to I6 fail and the workflows cannot start)
and the merge is refused. `a+c` is refused before any judge: both branches are in `integration` (and both edit
`service/app.py`). The shared assumption, that the service publishes `/openapi.yaml`, is in no contract, which is the
point: disjointness proves which evidence carries over, never that the merged application works. `validation/handoff.py`
re-runs all three and compares them with `recorded/`; `validation/judge_wrong.py --handoff` holds the two refused merges
to exactly their reasons; `validation/evidence_reuse.py` shows a cacheable result reused from the second of two offered
evidence directories when only it matches.

**Limits.** Partitions are declared, so a change whose effect crosses partitions through an undeclared channel is caught
only by the re-run checks, which is why they always re-run. Two branches may not touch one partition, and textual
conflicts are found per file, not per hunk; a finer partition is a pack change. A reused record names the run that first
produced it, not the directory it was read from.

## 9. Evaluator changes and compatibility

New identifiers (added to `COMPATIBILITY.md`): `pith.saboteur-packet/v1`, `pith.redteam-report/v1`,
`pith.redteam-gaps/v1`, `pith.divergence/v1`, `pith.trace/v1`, `pith.trace-provenance/v1`, `pith.merge-report/v1`. Optional additions:
`composition.yaml: runtime`, `pith.composition-report/v1: runtime`, `pith.task-packet/v1: counterexample.trace` and the
fields beside it and `disclosure`, `pack.yaml: redteam | traces | packet | partitions`, `evidence.json: reused_from_all`,
`app_gate.py --reuse` repeatable, `gate/interleave.py` (a library and `serve`), CLI subcommands `pack
redteam`, `packet distill`, `trace harvest | replay`, `handoff merge`, `compose verify | stagger`.

Packs: every release changes because `gate/` changes. The reservation pack 0.12.0 → 0.13.0 (the `sqlite-occ` choice and
its check, partitions, traces, the shadow monitor, the deterministic lifecycle test); booking 0.12.0 → 0.13.0 and quota
0.2.0 → 0.3.0 (deterministic interleaving tests; a previously accepted application with a latent race is now refused,
which `COMPATIBILITY.md` calls a stricter check: pre-1.0 practice is a minor version, and no contract record's meaning
changed, so no record version and no `contract_version` changes); approval and the tally demonstrations are resealed
without other change. One evaluator change alters evidence keys beyond the new code: a manifest choice is now keyed on the
manifest (§ 8), so a changed choice is never reported as holding; such checks were never reused.

## 10. Validation

| Capability | Runner | Negative it must refuse, for exactly its reason |
|---|---|---|
| runtime composition, staggered migration | `validation/compositions.py`, `judge_wrong.py --composition` | `split-saga-leak`, `orphan-receipt-on-abort` (and their TLA+ twins), `touches-quota-store`, `drops-compensated` |
| redteam ratchet | `validation/redteam.py` | the under-specified pack (refused for release), then the promoted `over-grant-by-one` |
| distilled packets | `validation/test_packet.py`, `validation/packets.py` | any leak, in every category run and every known-wrong evidence directory |
| deterministic interleavings, OCC | `validation/interleavings.py`, `profiles/sqlite_occ/tests/test_occ.py` | `check-then-insert`, `unlocked`, `split-decision`, `blind_write`, `unversioned_read`, `receipt_outside_cas` |
| shadow and harvest | `obligations/boundary/test_monitor.py`, `validation/shadow.py` | the drifted club desk |
| fork-join | `validation/handoff.py`, `validation/evidence_reuse.py`, `judge_wrong.py --handoff` | the `agent-b` + `agent-c` merge, the `agent-a` + `agent-c` merge |

CI: a new job `assurance` runs the interleavings and the shadow; the `packs` job runs the red-team ratchet, the runtime
composition and the fork-join handoff; the `judge` job judges `build-occ` and runs the OCC profile tests. `validation/
matrix.py` keeps its mutation cases (two new: a generated monitor without shadow mode; a custom adapter deciding outside
its lock) and lists every capability's runner (`--runners`).

## 11. Exit criteria

| Criterion (the request's definition of done) | State |
|---|---|
| This RFC complete and accurate | **Met**: written before the implementation, each section corrected to what was built (the deviations are in § 1 and in each track). |
| All six tracks implemented in the repository's conventions | **Met** (§§ 3–8); every new capability is evaluator code reading pack or composition declarations, or pack policy. |
| `validation/matrix.py` covers every new capability | **Met as § 1 reads it**: a runner per capability wired into CI, listed by `matrix.py --runners`, and two new mutation cases. |
| `validation/domain_free.py` passes | **Met** (6 packs, 180 terms); it caught "sqlite", "ledger" and "service/run.py" in new evaluator code, each removed by making the pack declare it. |
| `validation/judge_wrong.py` passes, every new negative refused for exactly its reason | **Met** for every pack and the new `--composition` and `--handoff` modes; promoted gaps carry `promoted_from`. |
| `evidence_reuse.py` and `handoff.py` pass, sequential and fork-join | **Met** (four reuse checks; 30 handoff expectations). |
| Every `frozen.sha256` and `release.seal.json` updated through the tooling | **Met**: `gate/release.py seal` and `gate/catalog.py pin` only; seals match on disk and in built releases. |
| Verified | macOS and arm64 Linux, every CI step but the x86 isolation container, plus the matrix (`docs/VALIDATION.md`, v0.13.0). |

## 12. What this does not show

How agents behave with these tools: no model runs in CI; the saboteur packets and the fork-join branches are scripted,
like RFC 0004 § 7's handoff, and nothing here is a measurement. That a gap closes says the gate got stronger against
that mutant, not that the pack is adequate; that a merged application is accepted says it was judged, not that every
merge of those partitions works. Whether the isolation profile's network-less container lets the frozen monitor suite's
loopback sidecar test run was not checked here (the `isolated` CI job will say). Everything was designed and checked
with the maintainer's own tooling, partly by delegated agents whose work was reviewed and re-run; none of it has had the
independent review `GOVERNANCE.md` requires before a pack leaves `draft`.
