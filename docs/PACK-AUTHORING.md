# Writing a contract pack

For someone adding a new domain to Pith without changing the evaluator. The format is in
`docs/rfc/0001-contract-packs-and-evidence.md`; what the existing packs needed is in `docs/rfc/0002-generality.md`.
`packs/booking/` (a verified core the candidate builds on) and `packs/approval/` (a model the candidate's own code
is judged against) are the two worked examples to copy from.

If you find you need to edit anything under `gate/` to express your obligations, stop and write down what and why:
that is the finding M3 is looking for (RFC 0002 § 7). Do not work around it inside your pack.

## 0. Start from the scaffold

```bash
python3 gate/cli.py pack new <name> --out packs/<name>     # a complete, judgeable draft pack with a small example contract
python3 gate/release.py seal --pack packs/<name>
python3 gate/cli.py pack check packs/<name>                # errors make it unfit to judge with; warnings are a reviewer's questions
validation/judge_example.sh --pack packs/<name> packs/<name>/examples/basic ../ev-basic
python3 validation/judge_wrong.py --pack packs/<name> ../ev-wrong
```

Then replace the example contract (a bounded tally) with yours, section by section below, keeping `pack check` free of
errors as you go. RFC 0003 § 5 describes the workflow.

## 1. Decide what the oracle is

Pick the native language your requirements are precise in, and what the candidate's code is held to:

| Shape | Oracle | The candidate's service is judged against | Example |
|---|---|---|---|
| Verified core | Dafny spec + a core you prove | a translation of the core (Python, JavaScript), by black-box property tests | `packs/booking` |
| State machine | TLA+ spec | an executable reference model you show equal to the spec within bounds (`harness/refines.py`) | `packs/approval` |
| Design obligations | TLA+ actions the candidate's own design must extend | the proven kernel, plus model checking of the candidate's design | the root pack |

Write `INTENT.md` first, in plain words: what the contract promises, each promise tagged with the id of its
contract record, and what it explicitly does not promise.

## 2. Lay out the directory

```
packs/<name>/
  pack.yaml          the manifest: policy dirs, candidate dirs, checks, statuses, contract records
  INTENT.md          reviewed prose (not an oracle)
  <oracle dirs>      spec/ or model/: the formal statements, wrong designs, traces, assumptions
  harness/           SERVICE.md (the service contract), a supervisor, black-box tests, a frozen client
  delivery/          the application contract (a page, a CLI, ...) and its adapter
  examples/          at least two conforming applications, and examples/wrong/ with expected.yaml
```

Everything in `policy_dirs` is frozen; the candidate owns `candidate.owned_dirs` and `app.manifest.yaml`.

## 3. Write the checks

Use the kinds the evaluator has (`command`, `files_present`, `source_rules`, `tlc`, `regenerated`,
`manifest_choice`, `manifest_commands`, `adapter`, `attestation`). Most tools fit `command`: exit 0 is the verdict,
`count` pulls a number into the report, `expect_exit: nonzero` says the command must fail (a wrong design must be
rejected), and `each: {glob: ...}` makes one check per matching file.

For every check: `status` (which status it counts toward), `method` (proof, model-check, test, browser, review,
structural, policy), `inputs` (the globs it reads: under-declaring them makes evidence reuse unsound), `depends_on`,
`establishes` (contract record ids), and `cacheable: true` only if its result is a function of its inputs and tools.
Never mark a check that starts the candidate's service cacheable.

So the task packet tells an agent whose problem a failure is (RFC 0003 § 2): mark checks of your own oracle
`about: release` (a failing proof or model check is the release's defect, not the candidate's); mark coverage-style
checks `failure_category: not_exercised`; have your delivery adapter return `failing` (the obligation ids) and a
`failure_category` when it knows better than `violation` (an unavailable browser is `toolchain_unavailable`); and put
the contract records each harness test bears on in its docstring (`"""Contract: A3."""`).

Every manifest key you allow needs a defined domain and evidence: a `manifest_choice` preflight, or an entry under
`parameters:` (`{domain, evidence}`). Allow `include` and `subsystem` if existing projects may adopt the pack
(`docs/ADOPTING.md`).

Statuses are yours: name them, say how each is computed (`all_pass` or `from_check`), and what value release
readiness needs. The approval pack has no human evaluation and a `model_assurance` status; the booking pack has the
same three statuses as the root pack.

## 4. Run the candidate's code through the evaluator

Start the service with `gate/service.py:Supervised` from your `harness/supervisor.py` (it runs the candidate as the
candidate's user, waits for readiness, and can SIGKILL and restart it on the same state). Run any other candidate
program with `gate/sandbox.py:run_as_candidate_full`. If a runtime needs a resource limit lifted (Node.js and
`RLIMIT_AS`), pass a `limits` override; say why in a comment. The harness must never import candidate code.

What a harness author needs to know before writing one:

- `command` checks run as the **judge's** user, with `{python}` = the judge's `sys.executable -I`, and a 900 s
  timeout per command. A pytest harness therefore runs as the judge and must start candidate code itself.
- The candidate's environment is scrubbed to `PATH HOME LANG LC_ALL TMPDIR`.
- **No service?** A library, CLI or batch pack runs each candidate program through `run_as_candidate_full`, which
  returns exit code, stdout and stderr; there is no stdin, so pass input as arguments (bounded by the kernel's
  128 KiB per argument). `packs/quota/` drives a library this way with frozen driver programs that import it; its
  split between behavioural assurance (what the library decides) and delivery (frozen consumer programs) is one
  way to draw the line.
- `INTENT.md` is outside `policy_dirs` in every pack so far, so it is reviewed prose but not frozen: a change to it
  does not change the release digest.
- `domain_free.py` matches contract ids case-sensitively and vocabulary as substrings: an id such as `Isolation`, or
  a word such as `limit`, collides with the evaluator's own words. Pick ids and terms that are specific to the domain.

## 5. Prove the pack rejects what it should

- **Wrong designs** next to the oracle (`spec/wrong/`, `model/wrong/`), each with one defect, each checked to fail.
- **Wrong applications** in `examples/wrong/`, each a conforming example with one defect marked `DEFECT`, and
  `expected.yaml` naming exactly where each is refused (`refused_at` + `failing_tests`) or which delivery
  obligations it fails (`must_fail`).
- **Traces** for review: concrete accepting and rejecting cases a reader can check against `INTENT.md` by hand,
  run on every judge, each wrong design differing from the oracle on at least one. Make that last part a check, not a
  comment (`packs/quota/harness/adequacy.py` runs each wrong core on its named trace; a wrong design that merely fails
  to verify may be failing for an unrelated reason). Have someone other than the person who wrote the formal
  statements read them before you seal.

## 6. Seal and validate

```bash
python3 gate/release.py seal --pack packs/<name>                       # the frozen list and release.seal.json
python3 validation/domain_free.py                                      # gate/ must not contain your vocabulary
validation/judge_example.sh --pack packs/<name> packs/<name>/examples/<app> ../ev-<app>
python3 validation/judge_wrong.py --pack packs/<name> ../ev-wrong       # every wrong app refused for exactly its defect
python3 validation/generality.py ../ev-*                               # one evaluator across the packs
```

List your vocabulary in `domain_vocabulary` so CI can hold the evaluator to it, and add your examples to the
`packs` job in `.github/workflows/gate.yml`.

## 7. Release review: not by you

A pack's author cannot certify their own acceptance checks. Before a release is published, someone who is not one of
`pack.maintainers` reads `INTENT.md`, the accepting and rejecting traces and the wrong candidates, and signs a review
of that exact release digest:

```bash
python3 gate/review.py keygen --out reviewer                                    # the reviewer, on their own machine
python3 gate/review.py sign-pack --key reviewer.key --release "$(python3 gate/release.py id --pack packs/<name>)" \
    --pack <pack id> --reviewer "name/role" --reviewed intent --reviewed traces --reviewed wrong --expires 2027-06-30 \
    --out packs/<name>/reviews/<name>.json
python3 gate/cli.py pack check packs/<name> --release --reviewer-key reviewer.pub      # stage: released
```

Any change to the pack changes its digest and invalidates the review.

## 8. Changing a released pack: routes and migrations

Give every contract record a `change` route and map the candidate's paths onto routes, so `gate/change.py` can tell a
developer what a change reaches before they make it:

```yaml
change_routes:
  - { paths: ["ui/**"], route: presentation, why: "the browser application: delivery and interaction checks" }
  - { paths: ["service/**"], route: integration, why: "the service: correspondence to the model" }
```

A new release that changes what the pack promises bumps the changed records' `version` (evidence for the old version
is then invalidated, `gate/evidence.py impact`) and, when deployments carry state, ships a migration: a spec in a
policy dir (format `pith.migration/v1`: the mapping from old state to new, how old retries and in-flight requests
behave, the rollback policy, and the `populate`, `migrate` and `verify` commands), declared under `migrations:` and
named by the record it establishes (`migration:`). `populate` drives the old release's service to produce real state;
`verify` judges the new service on it; the candidate supplies `migrate`. Ship known-wrong migrations too: a migration
that drops history usually passes the ordinary judge. `evolution/tally-v2` is the worked example and
`docs/rfc/0004-safe-evolution.md` § 4 the reference.

Where your pack is one component of a larger workflow, state the composition rather than assuming it:
`compositions/<name>/composition.yaml` and `python3 gate/cli.py compose check` (§ 3 of the same RFC).
