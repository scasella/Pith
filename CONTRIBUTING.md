# Contributing

Issues and pull requests are welcome. Please read `ARCHITECTURE.md` first.

## Ground rules

- **Frozen directories** (`kernel/`, `obligations/`, `gate/`, `profiles/`) change only through a release:
  edit, run `python3 gate/release.py seal`, re-run `docs/VALIDATION.md`'s matrix (`validation/matrix.py`), the
  examples (`validation/judge_example.sh`) and the known-wrong fixtures (`validation/judge_wrong.py`), and record
  the new release digest in `CHANGELOG.md`.
- **Known-wrong fixtures** (`examples/wrong/`) are first-class: a defect found by a review becomes a fixture with
  the exact obligations it must fail (`examples/wrong/expected.yaml`) before the fix to the checks ships.
- **Behavioural changes** to the core follow `INTENT.md` § How a behavioural change is made: spec, proof,
  adequacy candidates, traces, obligations, generator, monitor, in that order.
- **Evaluator bypasses** are security reports, not issues: see `SECURITY.md`.
- New examples under `examples/` contain only agent-owned files plus the claims file from a pinned run.
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
```

## Style

Python 3.12+, standard library where possible, no new runtime dependencies in `profiles/` or the service
contract without discussion. `python3 -m pyflakes gate obligations profiles kernel/gate` should be clean.
