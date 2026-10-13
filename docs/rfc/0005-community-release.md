# RFC 0005 — Community-ready release: governance, compatibility, catalog, experiments

| | |
|---|---|
| Status | Implemented in v0.11.0 (roadmap milestone M6). § 7 says which M6 exit criteria are met; most need people the project does not have yet. |
| Applies to | `GOVERNANCE.md`, `COMPATIBILITY.md`, `catalog.yaml`, `revocations.yaml`, `gate/catalog.py`, `gate/deploy.py`, `experiments/`, `validation/governance.py` |
| Builds on | RFCs 0001 to 0004. Nothing in their formats is withdrawn. |

## 1. What M6 asked

Multiple maintainers can publish, evaluate, upgrade and retire packs under a documented process. Stable
compatibility rules, maintained packs, governance, reproducible evaluation results. Run the empirical programme
alongside: three conditions, rotation across models and repeats, outcomes measured after a change, failures
published. A demanding 1.0 bar.

Most of this is about people: maintainers, reviewers, adopters, experiment participants. This release builds what
they need and makes the parts that can be mechanical, mechanical; it does not pretend the people exist.

## 2. Governance (`GOVERNANCE.md`)

Three roles (behavioral semantics, evaluator security, integration and developer experience), what each must not do,
and what needs whose approval: a pack release needs a signed review by someone who is not one of its maintainers; an
acceptance-policy change needs independent review; an evaluator change needs a second maintainer and every pack's
validation re-run. "Frozen" means immutable within a published release, not uncorrectable. Supported versions,
deprecation and retirement periods. Keys belong to people and are never committed. Discovered unsoundness is handled
as a security report: reproduce it as a known-wrong candidate, publish an advisory, revoke the affected releases with
the records they are unsound for, ship a release that refuses the candidate, and judge applications again (nothing
is grandfathered).

The document opens by saying what is true now: one maintainer holds every role, no change has had independent
review, and every pack is `draft`.

## 3. Compatibility (`COMPATIBILITY.md`)

Versioning for the project, packs (semantic; major when an accepted application could stop satisfying the contract),
contract records (bumped when meaning changes; evidence for the old version is invalidated) and releases (their
digest). The stable interfaces, each identified by a format string in the document, are listed with where each is
defined. Adding optional fields is allowed in a minor release; changing or removing anything takes a new format
identifier with the old one read for two more minor releases. Exit codes and failure categories are never renumbered.
Evidence is never upgraded in place.

## 4. Catalog and revocations (`catalog.yaml`, `revocations.yaml`, `gate/catalog.py`)

Each catalog entry (`pith.catalog/v1`) states a pack's scope, assumptions, examples, wrong candidates, supported
profiles, reference implementations, the evidence behind it, its upgrade policy, maintainers, reviews, status
(`supported`, `deprecated`, `retired`, `demonstration`) and the release digest it vouches for. An entry is never a
certification that an application using the pack is correct.

`catalog.py check` (CI) holds every entry to its pack: the digest is the sealed one, the listed files exist, the
maintainers match, and the **stage is derived, not claimed**: it must equal what `gate/cli.py pack check` derives,
which is `released` only with a valid independent review of that digest. An entry that claims `released` without one
is refused (`validation/governance.py` shows it). `catalog.py pin` rewrites the digests after a reseal.

`revocations.yaml` (`pith.revocations/v1`, append-only) lists revoked releases (with what they are unsound for),
evaluators, review keys and reviews. `catalog.py revoked --evidence DIR | --deployment FILE` reports whether a
judgement rests on something revoked, and `gate/deploy.py check --revocations FILE` reports such a deployment as not
covered. The repository's file is empty: nothing has been revoked.

## 5. The experiment harness (`experiments/`, `docs/EXPERIMENTS.md`)

The protocol (`pith.experiment-protocol/v1`): three conditions (prose; a trusted core with conventional tests; the
full Pith workflow), a task family of a build followed by a substantial change with populated state, common external
criteria that know nothing of Pith (so a baseline is never failed for lacking Pith's structure), full crossing of
models × tasks × conditions × repeats with the order rotated, one budget for all conditions, the primary outcome
(accepted, usable, and changed without maintainer repair) and the supporting measures (regressions, false acceptance
and rejection, interventions, setup failures, repair cycles, usage, evaluation and authoring cost), and publication
rules (every planned run published, failures and exclusions included; a holdout set maintained by someone else).

`experiments/harness.py`: `plan` (the crossed, rotated run list), `validate` (a run record against the schema and the
protocol: an intervention must say why the instructions were not enough), `analyze` (recomputes the primary outcome
from the stages, Wilson intervals, missing and abandoned runs reported), `dryrun` (the whole pipeline with two
scripted agents, labelled as measuring the harness only). The scripted dry run exercises each path: success, a false
acceptance that only the external criteria see (a migration that drops refusals, accepted by conventional tests), and
a repair cycle after the judge refuses the same migration.

## 6. Validation (`validation/governance.py`, CI job `packs`)

The catalog matches every pack; a claimed `released` stage is refused; evidence and a deployment resting on a release
revoked in a scratch revocations file are reported revoked, and the same deployment is covered without it; the
experiment harness runs end to end, labels itself a dry run, counts the false acceptance and the repair cycle; the
plan crosses every factor and rotates the first condition.

## 7. M6 exit criteria

| Criterion | State |
|---|---|
| Stable compatibility rules | **Written** (`COMPATIBILITY.md`); tested only in the sense that every format now carries its identifier. No external consumer depends on them yet. |
| Governance: roles, approval, supported versions, key and attestation revocation, unsoundness | **Written, with the mechanical parts enforced** (`pack check --release`, `catalog.py check`, `revocations.yaml`, `deploy.py check --revocations`). **Not practised:** one maintainer holds every role. |
| A curated catalog of maintained packs | **Built** (`catalog.yaml`: three supported packs; the outside author's quota pack and two demonstration releases as `demonstration`). All `draft`: no independent release review exists. |
| Reproducible evaluation results | Every validation in this repository runs in CI from a fresh checkout and writes its record. **Not met** for the empirical programme: no real-model runs. |
| Experiments: three conditions, rotation, repeats, outcomes after change, failures published | **Harness built and dry-run in CI. Not run.** It needs model access, budget, and people to run and publish it. |
| **Exit gate:** multiple maintainers publish, evaluate, upgrade and retire packs under the documented process | **Not met.** It needs a second maintainer and independent reviewers. |

The roadmap's proposed 1.0 bar, for the record: three structurally different seed families including independently
maintained non-payment packs (three families exist; none is independently maintained); a supported isolated evaluator
and stable contract and evidence interfaces (yes, and written down); demonstrated implementation variation and at
least one existing-project adoption (variation yes; adoption only the repository's own example, not an external
team's); working change, migration and evidence-invalidation processes (yes, demonstrated on one contract upgrade; since v0.12.0 on all four main packs, RFC 0006);
published multi-model experiments and external review of the evaluator and the pack-release process (no).

## 8. What the maintainer has to do next

1. Find one independent reviewer per pack and have them sign a release review (`gate/review.py sign-pack`); list it
   in `catalog.yaml`. That moves a pack from `draft` to `released` and exercises the governance for real.
2. Appoint a second maintainer for evaluator security, so evaluator changes stop being self-reviewed.
3. Run the conditions experiment with real models (`docs/EXPERIMENTS.md`) and publish every run.
4. Recruit external developers for the M4 trials (`docs/ADOPTING.md` § Recording a trial).
5. Commission an external review of the evaluator and the pack-release process.
