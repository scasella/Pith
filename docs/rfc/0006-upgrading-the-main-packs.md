# RFC 0006 — Upgrading the main packs: contract upgrades with populated state, the reservation kernels as a composition

| | |
|---|---|
| Status | Implemented in v0.12.0. § 7 says which roadmap criteria this closes and which still need people. |
| Applies to | `pack.yaml`, `packs/booking`, `packs/approval`, `packs/quota`, `compositions/reservation-kernels`, `validation/upgrades.py`, `validation/compositions.py`, `evolution/handoff` |
| Builds on | RFC 0004 (change classification, composition contracts, migrations, deployment records). No format changes, and no evaluator change: `gate/` is the v0.11.0 evaluator. |

## 1. What was left open

RFC 0004 § 8 met M5's exit gate on a demonstration contract (tally 1 → 2) and left three things open, each of which a
maintainer can close alone:

1. the reservation pack's two-kernel composition was stated only inside its design obligations, not in the
   composition format;
2. none of the main packs had had a contract upgrade, so none shipped a migration, and evidence invalidation had been
   shown only on a contract written to demonstrate it;
3. the agents in the handoff demonstration were scripted edits.

This release closes all three. It changes no format and no evaluator code: every pack is judged by the same `gate/`
as v0.11.0, which is itself evidence that the M5 mechanisms were general enough.

## 2. The reservation kernels as a composition contract (`compositions/reservation-kernels`)

The authorization kernel owns the request statuses and the holds; the posting kernel owns the posted total and what
each capture posted. Their permitted effects are the proven transitions (decide, release, consume a hold; post).
Two invariants span them: `INV1` (posted plus reserved never exceeds the limit, the pack's own record) and
`CaptureAgrees` (a request is `Post` in one kernel exactly when the other has posted its amount). `Decide` and
`Capture` must each be atomic across both kernels. Three known-wrong integrations each keep both kernels' local rules
and break exactly the shared invariants they name: `ignores-posting` decides against the holds alone (`INV1`),
`capture-forgets-posting` gives up the hold without posting (`CaptureAgrees`), and `split-capture` posts and releases
in two steps (both).

A restatement is only useful if it says the same thing as what it restates. `correspondence/` checks with TLC, in both
directions, that the integration and the pack's frozen design obligations (`obligations/design/CoreActions.tla`) have
the same behaviours under a refinement mapping, and that `ignores-posting` does not refine `CoreActions`
(`validation/compositions.py`, in CI). The frozen design obligations are unchanged; the composition contract is a
second, generic statement of the same agreement, not a replacement for it.

## 3. How a main pack's contract is upgraded

Each upgrade follows the route RFC 0004 defines for a behavioral change and the pack's own `INTENT.md`:

1. the spec or model first, with its proofs or model checks, and the known-wrong cores or designs the change must now
   reject;
2. contract records: a record whose meaning changes gets its next `version`; a new record starts at 1; a record whose
   meaning does not change keeps its version (its evidence is still invalidated, because the release changed);
3. a migration record `MIG1` with its spec `migrations/from-v1.yaml` (`from-v2.yaml` for the reservation pack, whose
   previous contract was `authorization-and-posting-core/v2`): mapping, old retries, the request in flight, rollback
   policy with its reason, and the frozen `populate`, `migrate` and `verify` steps;
4. every example updated to the new contract and given its migrate entrypoint; every existing known-wrong example
   still refused for exactly its defect; at least two known-wrong migrations, at least one of which passes the
   ordinary judge and is caught only on populated state;
5. `pack.version` gets its next minor version (pre-1.0, `COMPATIBILITY.md`) and `contract_version` its next version;
   the pack is resealed.

Rollback is `forward-only` for all four, each with its reason (§ 4); none claims reversibility it does not verify.

## 4. The four upgrades

### Reservation (0.11.0 → 0.12.0, `authorization-and-posting-core/v2` → `authorization-and-posting/v3`)

**Receipts for every write.** Version 2 kept a receipt for authorizations only: a client that retried a release after
losing the response was told `released: false`, which reads as "nothing was released" although the hold was gone. That
is the service-side twin of the receipt defects the interaction obligations exist for (I4, I5). New record `Receipts`
(version 1): every write answers with its receipt and a retry returns it with `replayed: true`. No proven kernel
changed (a receipt records what a kernel transition already did), so the kernels keep their own identity and the
contract gets a new name. Interface: `ReleaseResponse` and `CaptureResponse` gain `replayed`; the shipped profile keeps
receipts in the transaction of the write and refuses a database that was not migrated. New known-wrong application
`examples/wrong/retry-not-released`.

`MIG1` (`migrations/from-v2.yaml`): accounts and events kept byte for byte; each acknowledged write becomes its receipt,
read from the event log (the only place version 2 kept it); a version 2 client's retried release is now answered
`released: true, replayed: true` (a deliberate change, stated in the spec's `retries`); the request in flight at the
SIGKILL is decided at most once. Rollback forward-only: version 2 would write without receipts. The shipped profile
ships the migration (`profiles/sqlite/migrate.py`); the custom-adapter example (`build-b`) ships its own. Known-wrong
migrations: `skips-declines` (builds receipts only for authorized requests, judging declines "nothing to return";
passes the ordinary judge) and `stamps-history` (re-seals the event log with a contract label, so history is not
kept byte for byte).

<!-- BOOKING -->

### Approval (0.11.0 → 0.12.0, `approval-workflow/v1` → `approval-workflow/v2`)

**A quorum per document.** Version 1 approved a document at two distinct approvals of its current revision. A create
now takes an optional `quorum` (an integer from 2 to 5, 2 when absent); it is fixed for the document's life and an
edit restarts review against the same quorum. Records: `A3` 1 → 2 (its quorum, not two), `BoundaryConformance` 1 → 2
(the API changed), new `A9` (the quorum is chosen at creation and never changes; `QuorumFixed` in the TLA+ model).
The model now chooses the quorum at `Init` over `{2, 3}` with a fourth approver; two new known-wrong designs
(`WrongConstantQuorum` violates `BoundToRevision`, `WrongQuorumChanges` violates `QuorumFixed`); the refinement check,
three new traces (T12 to T14), lifecycle and boundary tests cover it.

`MIG1` (`migrations/from-v1.yaml`): every version 1 document becomes quorum 2 and keeps its revisions, status and every
approval ever recorded, stale ones included; every recorded result is kept and replayed (an old approval retried is a
replay, not `ALREADY_APPROVED`); the request in flight at the SIGKILL is decided at most once. Rollback forward-only:
version 1 cannot represent another quorum. The spec's migrate step is a frozen dispatcher that picks the Python or
Node.js entrypoint from the candidate's manifest; the existing-project example migrates its review tables and leaves
the project's own tables alone. Known-wrong migrations: `drops-stale-approvals` (judges superseded approvals dead data;
passes the ordinary judge), `drops-request-ledger` (clears the idempotency ledger; passes the ordinary judge) and
`creates-not-requalified` (leaves recorded creates without a quorum, so an old create retried is a conflict).
The trace review of M3 (`docs/reviews/m3-trace-review.md`) does not cover T12 to T14.

### Quota (0.1.1 → 0.2.0, `sliding-window-quota/v1` → `sliding-window-quota/v2`)

**A limit per key.** Version 1 held every key to one limit. A limiter now takes optional per-key limits
(`Limiter(limit, window, limits={...})`, the same in Node.js; each a whole number from 1 to 2^31−1) and answers
`limit_for(key)`, the key's own limit or the default, so a caller can report "N of M". The Dafny spec has
`LimitOf(c, k)` wherever it had `c.limit`, and the core re-verifies. Records: `Q0`, `Q1`, `Q3`, `Q4`, `Q5` 1 → 2 (each is
now against the key's own limit), `Persistence` 1 → 2 (dump and load carry the per-key limits),
`BoundaryConformance` 1 → 2 (malformed limits are refused as invalid arguments), new `KEYLIMIT`. Two new reviewed
traces (T9, T10), a new known-wrong core and library (`retry-default-limit`: the retry hint still uses the default limit).

The quota pack is a library: its state is what `dump` hands over. `MIG1` (`migrations/from-v1.yaml`): `populate` drives
the old library through the old release's own driver and writes its dumps, including one taken while the process kept
granting; the candidate's migrate entrypoint converts version 1 dumps in place (same limit, window, clock and live
grants; no per-key limits) and refuses anything else; `verify` checks that each migrated dump continues with version
1's decisions, that earlier instants still regress, that grants after a dump are not invented, and that per-key limits
work afterwards. There are no request ids to replay: old answers carry over because the clock and the live grants do.
Rollback forward-only. Known-wrong migrations: `clock-from-log` (rebuilds the clock from the newest grant; passes the
ordinary judge), `counts-only` (keeps counts and loses grant instants; passes the ordinary judge), `closed-expiry`
(re-prunes with a closed window). Three existing known-wrong libraries now also fail a new test that sees the same
defect, which their `expected.yaml` entries record.

This pack was written by an outside author. The upgrade was made by this project's maintainer, who is now listed as a
second maintainer of the pack; `AUTHORING-NOTES.md` says the author has not reviewed it, and the catalog keeps the
pack at `demonstration` until its author says otherwise.

## 5. What the upgrade check shows (`validation/upgrades.py`, CI job `upgrades`)

For each pack, against the release published at v0.11.0:

1. the previous release is rebuilt from the commit it was published at (`validation/upgrades.yaml: from_commit`) and
   has exactly the digest `catalog.yaml` recorded: the old side is the release that was published, not a
   reconstruction;
2. every old example is accepted under it, and the reference one is recorded for deployment;
3. the upgrade is classified `behavioral` before anything is judged again, naming the records that changed; the
   report says which old results still hold (those whose inputs and contract records the upgrade did not reach), and
   `upgrades.yaml` lists exactly which those must be;
4. the reference application judged under the new release with the old evidence offered (`--reuse`) is accepted and
   reuses nothing: evidence is bound to the release it was produced under, so even a result the classification says
   still holds is produced again;
5. the old deployment record does not cover the new artifact;
6. every example migrates state its own accepted old artifact produced (`gate/migrate.py`: unrecognised state refused,
   migrate, migrate again, verify, rollback stated);
7. every known-wrong migration is refused at verify for exactly its defect, and those marked `judged` pass the
   ordinary judge.

Two things this check found in the evaluator, recorded rather than changed (this release changes no evaluator code):

- The classification and the judge answer different questions across a release. For the reservation upgrade
  `change.py classify` reports fifteen old results as holding (the kernel proof and every design check: no input and
  no contract record of theirs changed), while the judge reuses none of them, because `--reuse` never crosses
  releases. Both are sound; the report's "holds" means "unaffected by this change", not "reusable". The tally upgrade
  could not show this, since it reached every record.
- `gate/migrate.py --old-evidence` requires every status of the old evidence to be at its ready value, including a
  human approval. For a pack whose acceptance includes an operator's signed approval (the reservation pack), a
  migration can only be bound to evidence a person has approved. `validation/upgrades.py` runs such migrations without
  `--old-evidence` and binds the report to the evidence itself (same artifact and release digests, and nothing but the
  approval missing), recording it as `bound_by` in the report. Whether `migrate.py` should accept evidence awaiting only
  people, as `deploy.py record --allow-not-ready` does, is an evaluator decision left to the maintainer.

## 6. A handoff between model agents (`evolution/handoff`)

The scripted handoff of RFC 0004 § 7 was done once by two model agents on the tally 2 release (`evolution/handoff/README.md`).
Agent A built an application from the release alone and was accepted on its first judge run; its migration, written
without any description of version 1's state, migrates the real version 1 state. Agent B took over with A's evidence
and task packet and a two-part request: it planned, made and classified the in-contract part (a log line; integration
route; the model checks reused, the service checks re-run) and refused the other (a larger bound for one counter) as a
contract change, noting that the route report could not tell it so because routes are declared by path. The agents'
code, B's change-impact reports and both agents' reports are committed; `validation/handoff.py` (CI) re-judges what
they produced and checks the record. No model runs in CI.

The run surfaced contract gaps in the tally 2 release that no scripted agent could have: its intent document and
known-wrong examples are not part of the release a candidate receives, and the version 1 state a migration must
recognise is described nowhere in it. They are recorded, not fixed here: the tally releases are demonstrations whose
digests other records cite, and the first one concerns what a release contains for every pack, which is an evaluator
decision for the maintainer.

## 7. What this closes, and what still needs people

| Criterion | State |
|---|---|
| M5: the reservation pack's composition restated as a composition contract | **Met** (§ 2), with a correspondence check against the frozen design obligations. |
| M5: migrations as behavioural transformations on the main packs | **Met for all four packs** (§ 4, § 5). |
| M5 exit gate: agent handoff | **Met once with model agents** (§ 6), alongside the scripted run in CI. One run, not a measurement. |
| 1.0 bar: working change, migration and evidence-invalidation processes | **Demonstrated on five contract upgrades** (tally and the four main packs), by the maintainer. |

Still needing people (RFC 0005 § 8, unchanged): an independent release review of each pack (every catalog entry stays
`draft`), a second maintainer, external developers for the M4 trials, the conditions experiment run and published with
real models across the protocol's models and repeats, and an external review of the evaluator and the pack-release
process. Every upgrade here was designed, implemented and checked by the maintainer's own tooling; none has been
reviewed by anyone else, which is exactly what `GOVERNANCE.md` says a release needs.
