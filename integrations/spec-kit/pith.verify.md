---
description: Judge the implementation against the Pith contract pack and act on the task packet (independent behavioural verification).
---

You are running Pith's verification step. Pith's evaluator, not you, decides whether the implementation conforms to
the contract. Do not edit `gate/`, `pack.yaml` or any directory the packet lists as frozen, and do not weaken a check.

1. Check the machine once: `python3 gate/cli.py doctor --json` (in an adopted project: `python3 "$PITH_RELEASE_DIR/gate/cli.py" doctor --json`).
   If `ready` is false, report the missing items and their `fix` to the user and stop.
2. Judge into a fresh evidence directory outside the project:
   - seed checkout: `python3 gate/cli.py verify --json -- --out ../pith-evidence-$(date +%s) --expected-release "$PITH_RELEASE"`
   - adopted project: `python3 "$PITH_RELEASE_DIR/gate/cli.py" verify --json -- --candidate . --out ../pith-evidence-$(date +%s) --expected-release "$PITH_RELEASE"`
3. Read the JSON packet on stdout.
   - `state` is `done`: report the statuses, `not_yours` (what a person still has to provide) and `coverage.statement`. Stop.
   - Otherwise act on `first_failure.category`:
     - `violation`: reproduce `first_failure.counterexample` (use `rerun.focused` if present), fix the cause in an `editable` directory, go to 2.
     - `not_exercised`: make the design or application actually reach the behaviour named in `first_failure.contracts`; go to 2.
     - `evidence_missing`: add what `first_failure.why` names; go to 2.
     - `contract_change`, `toolchain_unavailable`, `infrastructure`: not yours. Report the packet's `first_failure` to the user and stop.
4. Never report success unless the packet's `state` is `done`. Quote the contract record ids you worked on.
