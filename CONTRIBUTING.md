# Contributing

Issues and pull requests are welcome. Please read `ARCHITECTURE.md` first.

## Ground rules

- **Frozen directories** (`kernel/`, `obligations/`, `gate/`, `profiles/`) change only through a release:
  edit, run `python3 gate/release.py seal`, re-run `docs/VALIDATION.md`'s matrix (`validation/matrix.py`) and the
  three examples (`validation/judge_example.sh`), and record the new release digest in `CHANGELOG.md`.
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
validation/judge_example.sh examples/build-a ../evidence-a
```

## Style

Python 3.12+, standard library where possible, no new runtime dependencies in `profiles/` or the service
contract without discussion. `python3 -m pyflakes gate obligations profiles kernel/gate` should be clean.
