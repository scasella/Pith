# pith.quota: authoring notes (friction log)

I wrote this pack as an outside author. I worked from `docs/PACK-AUTHORING.md`, RFC 0001, RFC 0002 and the booking
and approval packs, starting from commit b64e50a. **I changed nothing under `gate/`**, and nothing in the other packs,
`validation/` or the root pack. This file is not part of the release: it is not in `policy_dirs`, so it is not frozen.

## The domain, and why

The domain is sliding-window quotas ("at most `limit` units per `window`"), delivered as a **library** in Python or
Node.js. The three existing packs never exercise these things:

- **There is no service.** The candidate ships `lib/limiter.py` or `lib/limiter.mjs`: no port, no HTTP, no state
  directory, nothing to crash and restart. Every existing pack, and §4 of the guide, assumes a service started
  through `gate/service.py`. A library is the case that most directly tests whether the evaluator is general or
  only service-shaped.
- **Time is an input.** Every call names `now`. The windows are half-open and they slide, and the clock must not run
  backwards.
- **A minimality obligation.** The retry hint must be the *earliest* instant at which the request would fit.
  Being safe is not enough: needless denials (an off-by-one window, counting denials) also break the contract.
- **A runtime-dependent obligation.** A Python limiter may be shared by threads. A Node.js limiter is synchronous,
  so the same obligation holds there by assumption.

## Result

| What | Result |
|---|---|
| `python3 gate/release.py seal --pack packs/quota` | release `0fee9b78c4f63efa…`, 46 frozen files |
| `python3 validation/domain_free.py` | `ok: gate/ is free of 4 packs' 133 domain terms and ids` |
| `judge_example.sh --pack packs/quota …/sliding-log-py` | contract_assurance, behavioral_assurance and application_delivery all `passed`; exit 0 (advisory, release_ready false: no enforced isolation) |
| `judge_example.sh --pack packs/quota …/tally-node` | the same three statuses `passed`; exit 0 |
| `judge_wrong.py --pack packs/quota` | 6 of 6 refused for exactly their defect (4 at `library.lifecycle` with the expected tests, 2 delivery-only: `[LW3]`, `[LI3]`) |
| evaluator digest | `a084c3d6ae5993ff…` for both quota runs, the same as an approval-pack run in the same tree |

## Changes I wanted to make to `gate/`, and what I did instead

None of these blocked me. Each one has a workaround that lives inside the pack. Each one is still a place where the
evaluator is shaped like a service, so I record them all.

1. **`gate/service.py:Supervised` only knows HTTP services.** Readiness is an `urlopen` of a path, stdin is
   `/dev/null` and stdout goes to a log. To drive a library I wanted one long-lived driver process per test session:
   it would import the candidate's library once and read commands as lines on stdin. *Needed:* a Supervised mode
   with piped stdin/stdout and readiness on a line of output. *Workaround:* one short process per program through
   `sandbox.run_as_candidate_full`, with the whole program as a JSON command-line argument. *Cost:* about 50 ms per
   program, roughly 10 s for 200 Hypothesis examples. The size of one program is bounded by the kernel's per-argument
   limit (`MAX_ARG_STRLEN`, 128 KiB).
2. **`sandbox.run_as_candidate_full` has no `input=` (stdin).** This is the same need as item 1, at a smaller scale.
   *Workaround:* `argv`. For the cross-process persistence workflow (LW4), the dump text goes from one consumer's
   stdout to the next consumer's `argv`. That works only while dumps stay small.
3. **No helper for "a directory the candidate may write" outside `Supervised`.** The `chown` to the candidate's
   identity in `Supervised.start` is private to that class. For LW4 I wanted consumer A to write a file and consumer
   B to read it. Under enforced isolation the judged root is not writable by the candidate, and writing my own
   `mkdtemp` + `chown` in pack code would copy security-relevant code into the pack, which RFC 0002 §4 moved into
   `gate/` to avoid. *Workaround:* the stdout-to-argv hand-over in item 2.
4. **No way to say why a wrong design must fail with Dafny.** The documented way, `command` +
   `expect_exit: nonzero` (booking's `core.adequacy`), accepts *any* failure: a typo, a type error, a missing loop
   invariant. That happened to me. My first `fixed_window.dfy` failed partly because of a `nat` subset-constraint
   error, not because of the contract. The `tlc` kind has `expect: {violated: X}`, and nothing like it exists for
   other tools. *Needed:* for example `require_output` / `forbid_output` regexes on `command`. *Workaround:*
   `harness/adequacy.py`, run through `command` with exit 0 expected. It requires three things: every Dafny error is
   an unproved postcondition; the unproved ones include one tagged with each obligation the file claims in its
   `REJECTED-BY:` header; and, run with `dafny run --no-verify` against `spec/TraceData.dfy`, the wrong core gives a
   different decision on the trace its `DIFFERS-ON:` header names. The third part matters because "Dafny could not
   prove it" is not "it is violated". `closed_window.dfy` is in fact safe, yet Dafny also reports `[Q0]` unproved
   for it.
5. **`source_rules` reads one fixed file.** I wanted to forbid wall-clock and randomness reads (`Date.now`,
   `time.time`, `Math.random`, …) everywhere under `lib/**`. `file` takes no glob and no `{item}`, and `each: {glob}`
   is not substituted into it (`kinds.k_source_rules` reads `c["file"]` literally). *Workaround:* none structural.
   Determinism is tested instead: the same program runs with real seconds passing between calls and must give the
   same results. That catches use of the wall clock, not every possible read of it.

## Where the docs were wrong, missing or misleading

- **The guide's §4 says "Start the service with `gate/service.py:Supervised`".** Nothing tells you what to do when
  there is no service. RFC 0001 §7 has one clause ("A CLI, library, service or mobile pack supplies a different
  adapter"), and the oracle-shape table in §1 has no library row. I had to read `gate/service.py`, `gate/sandbox.py`
  and `gate/kinds.py` to learn that `run_as_candidate_full` is the only other entry point, that `command` checks run
  as the judge's user (so a pytest harness runs as the judge and must start candidate code itself), that `{python}`
  is `sys.executable -I`, and that the candidate's environment is scrubbed to `PATH HOME LANG LC_ALL TMPDIR`. The
  guide should say all of this, because an author needs it before writing a harness.
- **The service/application split does not fit a library.** The statuses and examples assume "behavioural
  assurance = the service" and "application delivery = what a user sees". For a library I had to invent the split:
  what the library *decides* (`harness/`, against the verified core) and what *using* it is like (`delivery/`:
  frozen consumer programs for the documented quickstart, a backoff client, error handling, cross-process state,
  silent import, decisions as values, retained state). It works, but the docs gave me no guidance, and another author
  might draw the line elsewhere.
- **"Each wrong design differing from the oracle on at least one [trace]" (guide §5) reads as if it is checked.**
  In booking it is a comment in `spec/traces.dfy`, and nothing runs the wrong cores on the traces. I made it
  mechanical (item 4).
- **"Statuses are yours: name them" (guide §3) is not true for validation.** `validation/judge_wrong.py` hardcodes
  `behavioral_assurance == "refused"` for refused fixtures, `behavioral_assurance` + `application_delivery` for
  `must_fail`, and the adapter detail shape `delivery_detail.workflows[id] = {ok, evidence}`. A pack whose
  statuses or adapter detail are named differently cannot use the documented validation command. I kept those names
  (adding a third status, `contract_assurance`, as approval does with `model_assurance`), so it worked.
- **`failing_tests` in `expected.yaml` loses pytest parameters.** `judge_wrong.py` extracts names with
  `FAILED \S+::(\w+)`, which stops at `[`. So `test_reviewed_traces[T2_…]` and `test_reviewed_traces[T4_…]` both
  become `test_reviewed_traces`, and `expected.yaml` cannot say *which* reviewed trace a wrong application fails.
- **`domain_free.py` reports false positives for pack ids and vocabulary.** It searches contract ids
  case-sensitively and vocabulary as substrings. My natural contract id `Isolation` occurs in `gate/app_gate.py`,
  which is about the evaluator's own isolation, not my domain, so the check would have failed. I renamed it
  `InstanceIsolation`. The domain's central word, `limit`, cannot be listed in `domain_vocabulary`, because `gate/`
  says `limits` (rlimits) throughout. I listed `limiter` and `quota` instead, which is weaker. Neither problem is
  documented.
- **`INTENT.md` is not part of the release.** `pack.intent` points at it, but it is outside `policy_dirs`, so it is
  not frozen and not covered by the release digest, in my pack or in booking and approval. RFC 0001 calls it
  "reviewed prose", yet a change to it does not change the pin. I followed the existing layout. Either the docs
  should say this is intended, or the intent should be frozen.
- **Undocumented but needed:**
  - `depends_on` may name both `when`-alternative checks (`library.entrypoint.python` and `.node`), even though only
    one exists in a given run. I copied this from approval and it works, but nothing says so.
  - The Dafny Python runtime (`_dafny`) is the judge's `DafnyRuntimePython` package. Booking relies on it
    silently; I recorded it in `toolchain` as `dafny_runtime`.
  - Hypothesis writes `.hypothesis/` into the judged workspace. This is harmless, because it is in `CACHE_DIRS`.
  - A check's shell command has a 900 s timeout (`gate/app_gate.py:sh`).
  - `judge_example.sh` always creates its assembled candidate and release under `/tmp` (`mktemp`), whatever scratch
    location the author uses.
- **The guide says to add examples to CI (`.github/workflows/gate.yml`).** I did not: I was asked not to touch
  anything outside `packs/quota/`. A real author would need to make that edit.
- **Two smaller traps:**
  - `expect` is a Dafny keyword. My first trace datatype had a field named `expect` and failed to parse.
  - I nearly shipped `Traces.dfy` next to `traces.dfy`. Those two names collide on case-insensitive filesystems
    (macOS), and the judged copy would silently lose one. The data file is now `TraceData.dfy`.

## Obligations I could only partly express

- **Node.js atomicity** is an assumption (run-to-completion), not a test. A `Limiter` object cannot be shared
  across `worker_threads`. Recorded in `spec/tcb.yaml` and on the `Atomicity` record.
- **Python atomicity** is tested by bursts, not proven. The first burst design (one key, a few hundred calls) caught
  the `unlocked` fixture 1 time in 10, because each key gives one chance to race and the race window is a few
  bytecodes. The final test spreads 80 000 calls over 5 000 keys. It caught the defect in every one of my runs,
  each time over-granting by about 10. That is still probabilistic, and `expected.yaml` cannot express "probably".
- **"Never reads the wall clock"** is tested behaviourally only (item 5).
- **The oracle's performance limits the tests.** The verified core recomputes usage over the whole log, and its
  retry search is linear in the window. I chose that because it is obviously correct and easy to prove. As a result:
  - The extreme-values test (window 2^31 − 1) and the thread bursts state their expectations by hand, with the
    arithmetic in the test.
  - The oracle's burst computation stops at the first denial for each key, justified by [Q2] (a denial changes
    nothing).
  - Conformance uses windows of at most 15 instants.

  A faster verified core (a search over expiry points, with a proof of minimality) would remove the hand-written
  expectations. It was not worth the proof effort for this exercise.
- **Driver detection.** The library runs in the same process as the frozen driver, so a library that recognised
  the driver could behave differently there. A service can do the same with the harness's traffic, so this is not
  new, but it is closer here. Recorded in `spec/tcb.yaml`.
- **The traces are self-reviewed.** I worked out every trace by hand from `INTENT.md` *before* running it, and all
  8 held against the verified core on the first run. But no second person has read them. The guide asks for one,
  and RFC 0002 §7 records the same gap for booking and approval. `python3 harness/adequacy.py --print` prints them
  as Markdown for that review. Until someone does it, this pack is sealed for evaluation, not for release.

## What fitted without friction

- The pack format and `gate/pack.py` validation.
- `command` with `count` and `each: {glob}`, `regenerated` (the Python translation is reproduced byte-for-byte on
  every judge), `files_present` with `when`, `source_rules` for the trusted base, and `adapter`.
- `from_check` / `all_pass` statuses, including a third, pack-level status.
- Contract records, `run_as_candidate_full`, and the documented `RLIMIT_AS` override for Node.js.
- `release.py seal/build --pack` and `judge_example.sh --pack`.
- The approval pack's adapter shape carried over to a library adapter unchanged.
- The proof was quick: it verified (15 Dafny verification conditions) on the second attempt. The only fix was moving `now + r` out of
  quantifier triggers into a named predicate, `FitsAfter`.

## How long each part took (wall clock, about 50 minutes in total)

| Part | Share |
|---|---|
| Reading the guide, both RFCs, both packs, and then `gate/` (needed: see "Where the docs were wrong") | ~25% |
| Dafny spec, verified core and lemmas | ~10% |
| Wrong cores, the adequacy script, trace data and runners | ~15% |
| Library contract, drivers (Python and Node.js), oracle wrapper, lifecycle, boundary and conformance harnesses | ~20% |
| Two conforming libraries (Python sliding log; Node.js per-instant tallies in a separate module) | ~8% |
| Consumer contract, two consumer programs, delivery adapter | ~10% |
| Six wrong applications, including tuning the thread race until it was caught reliably | ~7% |
| Seal and validation runs | ~5% |

**An observation outside this pack.** The first time I judged `packs/approval/examples/approvals-py` in this tree,
`model.adequacy.self` failed ("WrongSelfApproval.tla no longer violates SeparationOfDuties"). TLC run by hand on the
same files reports the violation, and a second judge run passed every status. So that check failed once with
nothing changed, and I do not know why. I did not investigate further.

Reading `gate/` source took longer than any single authoring step except the harness. That time is the cost of
the gaps above.

## The v0.12.0 upgrade (2026-10-13): not written or reviewed by this pack's author

Everything above is the outside author's, unchanged. This section is not. For v0.12.0 the project's maintainer
(scasella) made the pack's first contract upgrade, 0.1.1 -> 0.2.0 (`sliding-window-quota/v1` -> `v2`), as one of the
four main-pack upgrades; `pack.yaml` now lists `maintainers: [outside-author, scasella]`. **The pack's author has not
reviewed this upgrade.** What it changed:

- **A limit per key.** `Limiter(limit=3, window=60, limits={"vip": 10})` (Node.js `limits: { vip: 10 }`) and
  `limit_for(key)` / `limitFor(key)`. The spec gained `Config.limits`, `LimitOf` and a `LimitReporter` trait; Q0, Q1,
  Q3, Q4, Q5, Persistence and BoundaryConformance went to version 2; KEYLIMIT is new. Two traces (T9, T10) and one
  known-wrong core (`spec/wrong/retry_default_limit.dfy`, the retry hint still against the default) with its library
  twin (`examples/wrong/retry-default-limit`). The existing wrong cores and libraries were moved onto the key's limit
  and keep exactly their defects.
- **The upgrade of a deployment** (MIG1, `migrations/`): a library's durable state is its stored dumps, so the
  migration converts a directory of version 1 dumps that the accepted version 1 library made. Forward-only.
- `limit` itself still cannot go in `domain_vocabulary` (gate/ says `limits`), so the new terms listed are
  `limit_for`, `limitFor`, `LimitOf`, `LimitReporter`, `per-key limit`, `lib/migrate`.
