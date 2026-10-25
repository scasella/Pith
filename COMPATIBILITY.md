# Compatibility

What other people's packs, tools and records may rely on, and how that changes. Applies from v0.11.0; the project is
pre-1.0, so the rules below are what a 1.0 would promise, practised now so they are tested before they are promised.

## Versions

- **The project** (`CHANGELOG.md`): `0.MINOR.PATCH` until 1.0. A minor release may change a stable interface only by
  the deprecation rule below; a patch release never does.
- **A pack** (`pack.yaml: pack.version`): semantic. Major when the contract changes in a way an accepted application
  could stop satisfying (a contract record's version bumped, a record removed, a check made stricter, a ready
  condition changed); minor when records or checks are added that every previously accepted application still
  satisfies, or the release changes only how a check runs; patch for documentation. `contract_version` names the
  contract itself (`tally/v2`) and changes exactly when a migration may be needed.
- **A contract record** (`version`): bumped whenever its meaning changes. Evidence for the old version is invalidated
  by the bump (`gate/evidence.py impact`, `gate/change.py`), even where the check and its inputs did not change.
- **A release** has no version of its own: it is its digest. Two releases with the same digest are the same release.

## Stable interfaces

Each is identified by a format string carried in the document itself; a consumer checks it and refuses one it does
not know.

| Interface | Identifier | Where it is defined |
|---|---|---|
| Contract pack | `pith.pack/v1` | `docs/rfc/0001-contract-packs-and-evidence.md`, `gate/pack.py` |
| Evidence | `pith.evidence/v1`, in-toto Statement v1 with predicate v1 | RFC 0001 § Evidence, `gate/evidence.py` |
| Claims | `app-claims.json` keys present in v0.6.0 or later | RFC 0001 § 7 |
| Task packet | `pith.task-packet/v1` | `gate/schemas/task-packet.schema.json` |
| Command line | `gate/cli.py` subcommands, `--json` output, exit codes 0/1/2/3 | `gate/cli.py` |
| Change impact | `pith.change-impact/v1` | RFC 0004 § 2 |
| Composition | `pith.composition/v1`, report `pith.composition-report/v1` | RFC 0004 § 3 |
| Migration | `pith.migration/v1`, report `pith.migration-report/v1` | RFC 0004 § 4 |
| Deployment record | `pith.deployment/v1` | RFC 0004 § 5 |
| Pack release review | `pith.pack-review/v1` | `gate/review.py` |
| Adoption trial | `pith.adoption-trial/v1` | `docs/ADOPTING.md` |
| Catalog, revocations | `pith.catalog/v1`, `pith.revocations/v1` | `GOVERNANCE.md`, `gate/catalog.py` |
| Experiment run | `pith.experiment-run/v1` | `experiments/schemas/run.schema.json` |
| Check kinds | the kinds in `gate/kinds.py` and their documented fields | RFC 0001 § 4 |
| Runtime composition (optional `runtime` block), its report section | `pith.composition/v1`, `pith.composition-report/v1` (unchanged identifiers) | RFC 0007 § 3, `gate/compose.py` |
| Saboteur packet, red-team report, gap record | `pith.saboteur-packet/v1`, `pith.redteam-report/v1`, `pith.redteam-gaps/v1` | RFC 0007 § 4, `gate/schemas/saboteur-packet.schema.json`, `gate/redteam.py` |
| Distilled task packet (optional fields) | `pith.task-packet/v1` with `disclosure: redacted` and `counterexample.trace` | RFC 0007 § 5, `gate/packet.py` |
| Divergence, trace, trace provenance | `pith.divergence/v1`, `pith.trace/v1`, `pith.trace-provenance/v1` | RFC 0007 § 7, `gate/trace.py` |
| Merge report | `pith.merge-report/v1` | RFC 0007 § 8, `gate/change.py merge` |

Not stable: anything under `validation/`, the human-readable text of claims and packets (`TASK.md`), file layouts
inside a pack beyond what `pack.yaml` names, and every Python function in `gate/` that is not a command.

## What a change to a stable interface must do

- **Adding** an optional field, a check kind, a subcommand or an enum value a consumer may ignore: allowed in any
  minor release; documented in the RFC that owns the format and in `CHANGELOG.md`.
- **Changing or removing** anything: a new format identifier (`/v2`), the old one still read (and, for documents the
  evaluator writes, still writable on request) for at least two minor releases, with the deprecation announced in
  `CHANGELOG.md` the release before the old one goes. The evaluator never reinterprets an old format's field.
- **Exit codes and categories** (the six failure categories, the four exit codes) are never renumbered or renamed;
  new ones are added only with a new packet format version.
- A pack written for `pith.pack/v1` keeps working with every evaluator that reads `pith.pack/v1`; an evaluator change
  that would alter a v1 pack's results is an acceptance-policy change (`GOVERNANCE.md`), not a compatibility detail.

## Evidence across versions

Evidence is never upgraded in place. It stays what it was: the record of a judgement by one release of one evaluator
over one artifact. Reuse (`--reuse`) is allowed only within the same release and evaluator. Moving to a new release
means judging again; `gate/change.py classify` says what the new release changed and `gate/migrate.py` what happens
to deployed state.
