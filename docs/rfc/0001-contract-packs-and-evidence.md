# RFC 0001 — Contract packs and structured evidence

| | |
|---|---|
| Status | Implemented in v0.7.0 (roadmap milestone M2). Open questions at the end are for M3. |
| Applies to | `gate/` (the evaluator), `pack.yaml` (the reservation pack), `evidence.json` and `statement.intoto.json` (every run) |
| Does not introduce | a specification language. Dafny, TLA+, Python harnesses and Markdown stay in their native forms. |

## 1. Why

Up to v0.6.0 the judge (`gate/app_gate.py`) was the reservation application's judge. It knew that the design module
was `design/Design.tla`, that it must extend `CoreActions`, that `status`, `held` and `posted` were core variables,
which twelve TLA+ predicates a design must not redefine, that `INV1` was the invariant the known-bad design must
violate, that the shipped profile was `sqlite`, that delivery meant a browser, and what `behavioral_assurance` was
scoped to. None of that is evaluation; all of it is the contract.

A second domain (M3) could not be added without editing the judge, so the judge could not be trusted to be the
same judge for both. And its evidence was one flat list of report lines: it could not say which claim rested on
which, or which claims a change to one file invalidated.

This RFC separates the two. The **evaluator** knows packages, artifacts, tools, checks, evidence, statuses and
policies. A **contract pack** supplies everything that is about the domain. The existing reservation seed is the
first pack and is judged with the same scoped results as before (§ 8).

## 2. Terms

| Term | Meaning |
|---|---|
| **Release** | The evaluator (`gate/`) plus one contract pack (`pack.yaml` and the directories it lists as `policy_dirs`). Its digest (`gate/release.py id`) covers every one of those files; operators pin it. |
| **Contract pack** | Versioned intent, behavioural semantics, obligations, assumptions, examples, wrong candidates, verification bindings and delivery adapters for one family of applications. |
| **Check** | One step the evaluator runs, declared by the pack: an id, a kind, the parameters the kind needs, the report text, which status it counts toward, and its evidence metadata. |
| **Kind** | How to run one sort of tool and interpret its result (`gate/kinds.py`). Kinds are tool-specific and domain-free. |
| **Adapter** | Pack code the evaluator calls for one check (`kind: adapter`). Delivery is an adapter, so a browser is one pack's choice, not a requirement of the method. |
| **Evidence record** | What one check established for one artifact, by which method, from which inputs, under which toolchain, resting on which other records (§ 6). |
| **Status** | A roll-up a reader acts on (`behavioral_assurance`, `application_delivery`, `human_approval` in this pack). The pack names them and says how each is computed and what value release-readiness needs. |

## 3. The pack manifest (`pack.yaml`)

`pack.yaml` sits at the release root and is frozen like every policy file. The evaluator reads it from the trusted
source (the pristine release with `--candidate`/`--policy-from`); a candidate cannot choose its acceptance policy.

| Field | Content |
|---|---|
| `format` | `pith.pack/v1` |
| `pack` | `id`, `version`, `title`, `contract_version`, `intent` (reviewed prose, not an oracle), `maintainers` |
| `policy_dirs` | Directories that are frozen pack content. The evaluator adds `gate/`. A pack cannot list `gate/`. |
| `candidate` | `owned_dirs` (with `app.manifest.yaml`, the deployment artifact) and `manifest_allowlist`. Disjoint from `policy_dirs`. |
| `tools` | Named tool locations read from the environment (`DAFNY`, `TLA2TOOLS`), substituted into commands as `{NAME}`. |
| `toolchain` | How to record each tool's version: a command (optionally a regex) or a Python package. |
| `pytest` | The pack's pytest invocation template, `{pytest}` in commands. |
| `statuses` | Each status: `rule` (`all_pass` over the checks that count toward it, or `from_check`: the outcome a check reports), the `passed` text for `all_pass`, and the `ready` condition (`equals` or `startswith`). |
| `refusal_status`, `completion_status` | Which status reads `refused` when a blocking check fails; which status decides exit 0. |
| `preflight`, `checks` | Ordered checks (§ 4). Preflight checks run before the isolation probe; checks after it. |
| `contracts` | Contract records (§ 5). |
| `domain_vocabulary` | Words that belong to the pack and must never appear in `gate/` (`validation/domain_free.py`, CI). |

`gate/pack.py` validates the manifest before anything runs: known kinds and methods, unique ids, dependencies
only on earlier checks, adapters only from frozen pack code, every `establishes` naming a contract record, every
`verified_by` naming a check. A malformed pack is a refusal (`policy · pack well-formed`).

## 4. Checks and kinds

Every check has `id`, `area` (a report label: the reservation pack uses `ring0`–`ring3`), `name`, `kind`,
`status` (or `null` for supplementary checks), `method` (`proof`, `model-check`, `test`, `browser`, `review`,
`structural`, `policy`) and `blocking` (default true). For evidence it has `inputs` (globs over the judged
workspace), `depends_on` (earlier check ids whose evidence this claim rests on), `establishes` (contract record
ids), `assumptions`, `tools` (toolchain entries the result depends on) and `cacheable`. Report text is `claim` and
`why`, with `{placeholders}` the kind fills in.

| Kind | Runs | Pass when | Parameters |
|---|---|---|---|
| `command` | a shell command in the judged workspace | exit 0 | `command`, `count` (regex → `{count}`), `export` (values from a JSON file into the report) |
| `files_present` | — | every file exists | `files` |
| `source_rules` | regexes over one source file | every `require` matches; no `forbid_lines` line; no `forbid_definitions` name defined | `file`, `require`, `forbid_lines`, `forbid_definitions` |
| `tlc` | TLC on a module + cfg copied to a scratch dir | `expect: no_error`, or `expect: {violated: X}` | `jar`, `copy`, `module_file`, `module`, `cfg` or `cfg_from` |
| `regenerated` | the pack's generator, then restores the files | generated files unchanged | `command`, `files` |
| `manifest_choice` | — | the manifest key takes an allowed value (or the default) | `key`, `default`, `choices` |
| `manifest_commands` | commands the manifest lists, as written | exit 0 (supplementary) | `key` |
| `adapter` | `run(ctx)` of a frozen pack module | the adapter reports no problems; its `status` is the check's outcome | `adapter`, `claims_key` |
| `attestation` | `gate/review.py` verification | always reports (approved / pending / rejected is the outcome) | `required_from`, `reviewer_context_from`, `claims_key` |

A check may carry `each: {list: FILE}` (one concrete check per name in the file; the reservation pack's seven
design-coverage checks) and `when: {manifest: {KEY: VALUE}}` (the sqlite profile tests run only for
`profile: sqlite`). Concrete ids are `group/item` (`design.coverage/CovRetry`); depending on `design.coverage`
means depending on all of them.

What stays in the evaluator, whatever the pack: the frozen-file and release-seal checks, the external pin, the
manifest allowlist, the artifact copy and digest, the isolation probe run under the candidate's identity
(`gate/sandbox.py`, `gate/isolation/`), the judged-copy-unchanged observation, and release readiness. These are
about the evaluation, not the contract.

## 5. The contract record

One record per protected requirement. It does not restate semantics: it points at them where they already live.

| Roadmap field | Record field | Reservation example (`INV1`) |
|---|---|---|
| Stable identity and contract version | `id`, `version` (+ `pack.contract_version`) | `INV1`, version 2 of `authorization-and-posting-core` |
| Human intent and explicit exclusions | `intent`, `excludes` (+ `pack.intent`) | "Posted plus reserved never exceeds the limit, under every interleaving…"; exclusions in `INTENT.md` |
| State model and precise semantics | `semantics`, by language | `dafny: kernel/spec/AuthSpec.dfy Valid [INV1]`, `tla: obligations/design/CoreActions.tla INV1` |
| Timing | `timing` | invariant of every reachable state; per transition in the proofs, across interleavings in the design |
| Inputs, observations, abstraction mappings | `semantics` entries + the pack's glossary | `kernel/glossary.yaml` binds requirement words to model expressions and observables |
| Required verification methods and evidence locations | `verified_by` (check ids); each check's `method`; the run's `evidence.json` | `kernel` (proof), `design.safety`, `design.adequacy` (model check) |
| Assumptions and their establishing mechanisms | `assumptions` | atomicity of core calls: `kernel/tcb.yaml`, established by `design.safety` and the profile tests, by test only |
| Satisfying and violating examples | `examples`, `wrong` | `kernel/adequacy/capture_keeps_hold.dfy`, `obligations/design/BrokenDesign.tla` |
| Customization rules and change dependencies | `change` (`presentation` / `integration` / `behavioral`, as in `CUSTOMIZATION.md`); the checks' `inputs` | behavioral: a change goes through `INTENT.md` § How a behavioural change is made |

Timing is stated where it matters and in words the reader can check against the native statement: "at the
atomic Decide step", "after acknowledgement, including across a crash and restart", "after the receipt is shown,
across later refresh failures". A timeout policy, a retry policy and an eventually-completes obligation are not
interchangeable, and the record does not pretend otherwise; this pack makes no liveness claim
(`kernel/tcb.yaml:not_covered`).

The reservation pack has 35 records: the eleven kernel tags, the five design predicates, five service and
boundary properties, W1–W6, I1–I6 and E1–E3.

## 6. Evidence

### Records

Each run writes `evidence.json` next to `app-claims.json`. One record per check:

```text
id, check, area, kind, method          what was run, and what kind of claim it is
result, claim, why, outcome            what it found (outcome: the status value an adapter or attestation reports)
contributes_to, establishes            which status it counts toward; which contract records it supports
assumptions, depends_on                what else the claim rests on
inputs, files, tools                   the declared globs; {path: sha256} of every file they matched; tool versions
own_key, key                           digests binding all of the above (below)
reused_from                            only when the record was carried over from earlier evidence (below)
```

plus the run: pack identity, release digest, evaluator digest, artifact digest, gate mode, authority, isolation
status, toolchain, statuses, `release_ready`, and a digest over the whole file.

So the report can say what the roadmap asks for: *this invariant is proved for these transitions* (`kernel`,
method proof, establishes `INV1`, assumptions `kernel/tcb.yaml`); *interleavings are model-checked within bounds*
(`design.safety`, depends on the design-structure checks); *persistence correspondence is tested under crashes*
(`lifecycle`, depends on `kernel`, `service.entrypoint`, `gen.current`); *UI target binding is exercised by these
scenarios* (`delivery`, establishes `I1`, depends on `lifecycle` and `boundary`).

### Keys and invalidation

```text
own_key = sha256(check definition minus report text, {path: sha256} of matched inputs, tool versions, python, evaluator digest)
key     = sha256(own_key, keys of the records it depends on)
```

Keys are computed for every check **before any check runs**, so files a check writes never change a key and the
same keys can be recomputed later for a changed workspace. A changed input changes that record's key and the key
of everything that rests on it. A UI edit therefore leaves the kernel proof and the design model checks intact
and invalidates delivery; a changed design module invalidates the model checks and nothing in the proof; a
changed generated schema invalidates the generator check, the monitor suite, the lifecycle and boundary harnesses
and, through them, delivery.

```bash
python3 gate/evidence.py impact --evidence ../evidence-001 --candidate .     # what still holds, what changed and why
python3 gate/evidence.py verify ../evidence-001                              # evidence.json digest and statement agree
```

### Reuse

`gate/app_gate.py --reuse PREV_EVIDENCE` lets a run stand on earlier evidence where that is sound, and only there:

- the check is `cacheable` in the pack (here: the kernel gate and the TLC checks, whose results are a function of
  their declared inputs and tools);
- the earlier evidence is intact (its digest matches), from the **same release** and the **same evaluator**;
- the earlier record **passed** and its **key is identical**.

A reused record says so (`reused_from`: the evidence directory, its digest and the key) in both `evidence.json`
and `app-claims.json`, and the report line ends in `(reused)`. Everything else runs. Checks that start the
candidate's service are never cacheable: their result depends on behaviour that file digests do not capture
(timing, the environment), and a re-run is what makes them evidence. Cross-release reuse is not allowed: a new
release may have changed what a check means even where its inputs did not.

Under-declared inputs would make reuse unsound. That is why reuse is opt-in per check, limited to kinds whose
inputs are files the pack names, and keyed on the evaluator's own code as well.

### Attestation format

`statement.intoto.json` is an [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md):
the subject is the judged artifact (`artifact/`, digest `pith-tree-sha256`: the tree digest the evaluator already
computes), and the predicate (`predicateType` `…/docs/rfc/0001-contract-packs-and-evidence.md#predicate-v1`) carries
the pack, release, evaluator and evidence digests, gate mode, authority, isolation status, statuses,
`release_ready` and, per record, its id, check, result, method, contract records and key.

The statement is **unsigned**: signing and distribution belong to the operator, who holds the keys. And provenance
does not itself prove behaviour. The statement says which checks found what for which artifact; what those checks
are worth is in the records' methods, scopes and assumptions.

## 7. Delivery is an adapter

`obligations/app/delivery_adapter.py` is the reservation pack's delivery adapter: the structural SPEC lint, the
browser workflows W1–W6 and the interaction obligations I1–I6 under injected faults. It returns a status
(`passed`, `failed`, `incomplete`), its problems, the report text, the detail the pack wants in
`app-claims.json:delivery_detail`, context for human reviewers, and its own release conditions (here: the browser
was contained, by Chromium's sandbox or a separate user under the enforced profile). The evaluator turns these
into a check, a status and a release-readiness condition without knowing a browser was involved. A CLI, library,
service or mobile pack supplies a different adapter.

The adapter runs in the judge's process, as pack code from the pristine release. It is trusted the way the rest
of the pack is trusted: by the release pin and review, not by the evaluator.

## 8. The reservation seed as a pack

| v0.6.0 | v0.7.0 |
|---|---|
| `gate/policy.yaml` (paths) + reservation logic in `gate/app_gate.py` | `pack.yaml` (checks, statuses, contract records); `gate/` is domain-free |
| `obligations/isolation/` | `gate/isolation/` (the evaluator's environment, not the contract) |
| identity and rlimits in `obligations/service/supervisor.py` | `gate/sandbox.py`; the pack's supervisor imports it |
| ring-3 aggregation in the judge | `obligations/app/delivery_adapter.py` |
| one list of report lines | the same lines, plus `evidence.json` and `statement.intoto.json` |
| release = kernel + obligations + gate + profiles | release = gate + pack.yaml + `policy_dirs`; `release.seal.json` format 2 names the pack |

`app-claims.json` keeps every key it had (`checks`, the three statuses, `delivery_detail`,
`human_approval_detail`, `ring0_scope`, `isolation`, `release_ready_missing`, …) and adds `pack`, `evidence` and
`evidence_digest`; each check line gains its pack `id`.

**Exit gate, as checked.** `validation/compare_m1.py` compares every example and known-wrong fixture judged by
this release against the record of the v0.6.0 judge (`validation/baselines/m1.json`): every check (area, name,
result, claim text with digests masked), every status, the failing delivery obligations, `release_ready` and
`release_ready_missing`. Two claim texts differ, by design: the frozen-files line names the new policy layout,
and the isolation line names the pack's policy dirs the probe now also tries (`profiles/` was not probed before)
and the moved README. `validation/domain_free.py` checks that no pack vocabulary, contract id or check id occurs
anywhere in `gate/`. `validation/matrix.py` runs the 19 wrong candidates against the new judge. Results are in
`docs/VALIDATION.md`.

## 9. Limits and open questions (for M3)

- **One pack per release.** M3 adds two more domains. Either each gets its own release (simplest; the pin already
  identifies the pack), or a release carries several packs and the operator's pin names one. Undecided until a
  second pack exists.
- **Kinds are what this pack needed.** A pack that needs another tool (a different model checker, a property
  tester with its own exit conventions) needs a new kind, which is an evaluator change and a new release.
  `command` covers most tools whose exit code is the verdict.
- **Inputs are declared by hand.** An under-declared input makes `impact` optimistic and would make reuse
  unsound; § 6 limits reuse accordingly. Deriving inputs from tools (Dafny's include closure, TLC's module list)
  would be better and is not done.
- **`area` labels and the three statuses are this pack's.** Another pack may have no `ring1`, no human
  evaluations, or a fourth status. The evaluator supports that; nothing exercises it yet.
- **Contract records are references, not checked content.** The evaluator checks that ids and check names are
  consistent; it does not check that `intent` matches `semantics`. That is the human review the roadmap keeps.
- **No pack compatibility rules yet.** Version fields exist; what a minor vs. major pack version may change, and
  how evidence is carried across versions, is M5–M6 work (§ 6 refuses cross-release reuse in the meantime).
- **Composition is still in the design model.** Records for `INV1` say where it is checked; a pack-level
  composition contract between independently authored packs is M5.
