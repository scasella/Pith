# Contributing

Issues and pull requests are welcome. Please read `ARCHITECTURE.md` first.

## Ground rules

- **Frozen files** (`pack.yaml`, `gate/`, and the pack's `policy_dirs`: `kernel/`, `obligations/`, `profiles/`) change
  only through a release: edit, run `python3 gate/release.py seal`, re-run `docs/VALIDATION.md`'s matrix
  (`validation/matrix.py`), the examples (`validation/judge_example.sh`) and the known-wrong fixtures
  (`validation/judge_wrong.py`), and record the new release digest in `CHANGELOG.md`.
- **The evaluator stays domain-free.** `gate/` must not name anything the pack is about: CI runs
  `validation/domain_free.py`. A check a pack needs is declared in `pack.yaml` with an existing kind; a new kind
  of tool is an evaluator change (`gate/kinds.py`, `docs/rfc/0001-contract-packs-and-evidence.md` § 4).
- **Known-wrong fixtures** (`examples/wrong/`) are first-class: a defect found by a review becomes a fixture with
  the exact obligations it must fail (`examples/wrong/expected.yaml`) before the fix to the checks ships.
- **Behavioural changes** to the core follow `INTENT.md` § How a behavioural change is made: spec, proof,
  adequacy candidates, traces, obligations, generator, monitor, in that order.
- **Evaluator bypasses** are security reports, not issues: see `SECURITY.md`.
- New examples under `examples/` contain only agent-owned files plus the claims file from a pinned run (an adoption
  example also carries the project's own files, which the judge does not copy unless `include` names them).
- A harness test names the contract records it bears on in its docstring (`"""Contract: A3."""`); a known-wrong
  fixture's `expected.yaml` entry names the packet `category` and `contracts` it must produce.
- Keep the judge honest: a check that cannot fail is removed, not kept.

## Running the checks locally

```bash
bash bootstrap.sh && source .env
python3 obligations/boundary/generate.py    # the monitor suite tests the generated gen/out/monitor.py
python3 -m pytest obligations/boundary/test_monitor.py profiles/sqlite/tests/test_profile.py -q
rm -rf gen                                  # leave a fresh seed behind
node --test obligations/app/lib/test_pith_view.mjs
validation/judge_example.sh examples/build-a ../evidence-a
python3 validation/judge_wrong.py ../evidence-wrong
python3 validation/domain_free.py
python3 -m pytest validation/test_packet.py -q              # failure categories, counterexamples, the packet, include rules
python3 validation/packets.py ../evidence-packets           # one run per failure category; every packet schema-valid
python3 validation/adoption.py ../evidence-adoption         # the existing-project journey (packs/approval/examples/adopt-handbook)
for p in . packs/booking packs/approval evolution/tally-v1 evolution/tally-v2; do python3 gate/cli.py pack check $p; done
python3 validation/evolution.py ../evidence-evolution          # handoff, rewrite, contract upgrade with state, composition (M5)
```

## Style

Python 3.12+, standard library where possible, no new runtime dependencies in `profiles/` or the service
contract without discussion. `python3 -m pyflakes gate obligations profiles kernel/gate validation` should be clean.
