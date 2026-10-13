# Governance

How packs and the evaluator are published, reviewed, supported, corrected and retired. The aim (roadmap M6) is that
several maintainers can publish, evaluate, upgrade and retire packs under a written process, and that nobody,
including the project's author, certifies their own acceptance checks.

**Where this stands (v0.11.0).** The project has one maintainer, so every role below is held by the same person
and no change has yet had the independent review this document requires. The process is written and the tools that
enforce its mechanical parts exist (`gate/cli.py pack check --release`, `gate/review.py sign-pack`,
`gate/catalog.py`, `revocations.yaml`). Until a second maintainer and an independent reviewer exist, every pack in
`catalog.yaml` is `draft`, and the project says so rather than treating its own review as independent.

## Roles

Three responsibilities, kept separate so that no one approves their own work in an area that decides acceptance.
They can begin as hats one person wears; they become separate people as the project grows, and the first
appointments are what M6's exit gate is waiting on.

| Role | Owns | Must not |
|---|---|---|
| **Behavioral semantics** (per pack: the pack's `maintainers`) | `INTENT.md`, contract records, models and specs, traces, known-wrong candidates, migrations | review their own pack's release |
| **Evaluator security** | `gate/`, the isolation profile, the release and seal format, `SECURITY.md` reports, revocations | merge an evaluator change they wrote without a second reviewer |
| **Integration and developer experience** | the CLI, task packets, templates, integrations, adoption and authoring guides | change acceptance (statuses, checks, contracts) through a "developer experience" change |

## What needs whose approval

| Change | Approval |
|---|---|
| A pack release (any change to a pack's digest) | the pack's maintainers, plus a signed release review by someone who is **not** one of them (`gate/review.py sign-pack`, covering intent, traces and wrong candidates), before `catalog.yaml` may list the release as `released` |
| An acceptance-policy change: a check, status, ready condition, contract record or its version, `change_routes`, a migration | independent review (as above); a behavioral change also follows the pack's `INTENT.md` (spec, wrong candidates, traces, then checks) |
| An evaluator change (`gate/`) | evaluator security plus one other maintainer; `validation/domain_free.py`, the matrix and every pack's examples and wrong candidates re-run; a new release of every pack it ships with |
| A change to `COMPATIBILITY.md`'s stable interfaces | all three roles; a deprecation period as that document says |
| A catalog status change (supported, deprecated, retired) | the pack's maintainers, announced in `CHANGELOG.md` |
| A revocation | evaluator security, immediately; reviewed by another maintainer afterwards |

A pull request that changes acceptance says so in its title. Review comments that are about acceptance are answered
in the pull request, not elsewhere.

## Releases and support

- **"Frozen" means immutable within a published release**, not uncorrectable. A correction is a new release with a
  new digest; the old release stays reproducible and its evidence stays what it was.
- Supported versions: the latest release of each `supported` pack, and the previous one for 90 days after a new
  release (so deployments can upgrade through its migration). A `deprecated` pack gets security and unsoundness
  fixes only, for at least 180 days. A `retired` pack gets nothing; its catalog entry stays, with the reason.
- Each release's digests are in `CHANGELOG.md`, and the validation record behind them in `docs/VALIDATION.md`.

## Keys, attestations and revocation

- Review keys (operator approvals of applications, `gate/review.py sign`; pack release reviews, `sign-pack`) belong
  to people, are generated on their machines and never committed. Public keys a pack's operators trust are
  distributed out of band; the catalog records only which reviewer signed which release.
- `revocations.yaml` (format `pith.revocations/v1`) lists revoked release digests, revoked review keys (by public-key
  digest) and revoked attestations, each with the date, reason and advisory. `gate/catalog.py revoked` checks an
  evidence directory or a deployment record against it, and `gate/deploy.py check --revocations` refuses a
  deployment resting on a revoked release or attestation. Revocation is append-only: an entry is never deleted, a
  mistaken one is superseded by a later entry.
- A compromised key: revoke it, list every release review and attestation it signed (the catalog and evidence name
  them), and re-review those releases with another key.

## When unsoundness is found

Unsoundness is a way for an application that violates a contract record to be accepted: a weak check, a wrong model,
a harness assertion that cannot fail, an evaluator bypass. It is handled as a security report (`SECURITY.md`):

1. Reproduce it as a known-wrong candidate that the current release accepts.
2. Publish an advisory naming the affected releases, contract records and checks; add the affected release digests to
   `revocations.yaml` with `effect: unsound-for: [record ids]`.
3. Ship a new release whose checks refuse the candidate (the candidate becomes a fixture), with a migration if state
   is affected.
4. Existing evidence for the affected records is no longer a basis for acceptance: `catalog.py revoked` reports it,
   and `gate/evidence.py impact` against the new release invalidates it. Applications are judged again; nothing is
   grandfathered.

Revoking a release does not delete its evidence: it says that evidence no longer supports the claims it made.

## The catalog

`catalog.yaml` lists the packs the project maintains. An entry is a statement about the pack, never a certification
that every application using it is correct. `python3 gate/catalog.py check` holds each entry to its pack: the
release digest is the sealed one, the listed examples and wrong candidates exist, the stage it claims is the stage
`pack check` derives, and nothing listed is revoked. Contributions that improve the method are the ones the catalog
records against a pack: a new counterexample, a clearer intent, a smaller trusted boundary, a reproducible profile, a
difficult migration.
