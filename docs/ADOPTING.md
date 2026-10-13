# Adopting Pith in an existing project

For a team with a working codebase that wants **one** workflow in it judged against a contract pack, without
rebuilding the project around Pith. The format is in `docs/rfc/0003-adoption-and-agent-feedback.md` § 6; the worked
example is `packs/approval/examples/adopt-handbook` (a handbook application adopting `pith.approval` for its review
workflow; `PITH.md` there is its adoption record).

What you get is narrow on purpose: evidence about the behaviour the pack's contract records describe, for the code
you name, reached through the pack's entrypoints. Nothing else in your repository is covered, and the report says so.

## 0. Prerequisites

A Pith checkout (for the evaluator and the packs) and a **pristine release** of the pack you adopt, built outside your
project and kept there:

```bash
git clone https://github.com/scasella/Pith && cd Pith && bash bootstrap.sh && source .env
python3 gate/cli.py doctor --pack packs/approval          # what is missing on this machine, and how to fix it
python3 gate/release.py build --pack packs/approval --out ../pith-approval-release
RELEASE="$(python3 gate/release.py id --pack packs/approval)"     # pin it; keep it out of an agent's reach
```

## 1. Identify the operation

Pick one workflow whose rules the pack's `INTENT.md` states, and the code that implements it. Read the pack's
contract records (`python3 gate/cli.py adopt` lists the behavioral ones) and its service contract (for
`pith.approval`, `harness/SERVICE.md` and `delivery/CLI-CONTRACT.md`). Where your behaviour differs from the
contract, decide now: change the code, or this pack is not the right one.

## 2. Prepare the project

```bash
python3 gate/cli.py adopt --release ../pith-approval-release --project ~/src/handbook \
    --subsystem "review of policy documents (handbook/reviews.py), through service/ and cli/" --include handbook
```

`adopt` writes `app.manifest.yaml` (with `include` and `subsystem`) and `PITH.md` (the adoption record), and lists the
entrypoints still to write. It never copies the release into your project and never overwrites a file. It refuses
when your code lives in a directory named like one of the pack's policy dirs (for `pith.approval`: `model/`,
`harness/`, `delivery/`), because in the judged workspace that directory is the pack's.

`include` names the code your entrypoints import. Keep it as small as the workflow allows: everything under it is
copied into the judged artifact and digested, so a change there invalidates the evidence (`gate/evidence.py impact`).

## 3. Attach the independent checks

Write the entrypoints the pack's harness starts (for `pith.approval`: `service/run.py` and `cli/main.py`) as thin
adapters over your code: they map the pack's API onto your functions and hold no rules of their own. Then judge
with the pristine release:

```bash
python3 -I ../pith-approval-release/gate/app_gate.py --candidate ~/src/handbook --out ../ev-1 --expected-release "$RELEASE"
cat ../ev-1/TASK.md
```

Each run ends with a task packet: the first failure, its category (`violation`, `not_exercised`,
`evidence_missing`, `toolchain_unavailable`, `contract_change`, `infrastructure`), the contract records it bears on, a
minimal counterexample and the rerun command. A `toolchain_unavailable` or `infrastructure` failure is not your
code's; the others are.

## 4. Replace or strengthen

Fix what the packet shows in your code, never in the checks, and record each step in `PITH.md`'s table. In the
handbook example the second run found that approvals of an earlier revision counted toward the quorum after an edit
(`A3`); the fix was one query. When every status passes, `app-claims.json:coverage` states what was judged:

```json
{"subsystem": "review of policy documents (handbook/reviews.py), through service/ and cli/",
 "included": ["handbook"], "judged_paths": ["app.manifest.yaml", "cli", "handbook", "service"],
 "statement": "evidence covers only the behaviour of pith.approval's contract records, as exposed through the candidate's entrypoints, ..."}
```

"Pith is installed" never means the rest of the application is checked.

## Recording a trial

M4's exit gate is external developers completing a fresh-seed build and an existing-project adoption from these
instructions, with setup failures and interventions recorded. If you try it, record it in this form (one JSON file per
trial; `validation/adoption.py` writes one for its scripted run, which does not count as external) and send it to the
maintainers, failures included:

```json
{"format": "pith.adoption-trial/v1",
 "who": "your name or handle; your role; whether you have used Pith before",
 "pack": "pith.approval", "release_digest": "<the pinned digest>",
 "project": "what the project is (language, size, how old)", "journey": "fresh-seed | existing-project",
 "instructions": "which documents you followed",
 "steps": [{"step": "...", "command": "...", "exit": 0, "seconds": 0}],
 "setup_failures": [{"what": "...", "how resolved": "...", "minutes lost": 0}],
 "interventions": [{"who": "a maintainer | you | an agent", "what": "...", "why the instructions were not enough": "..."}],
 "agent": {"model": "exact model id", "budget": "...", "attempts": 0} ,
 "outcome": "accepted | abandoned | not accepted", "notes": "..."}
```

An intervention is anything you needed that the published instructions did not give you: a maintainer's answer, a
workaround, a change to Pith. Those are the findings M4 is after.
