# The conditions experiment

What the roadmap's empirical programme asks, how `experiments/` runs it, and what has and has not been run.
Protocol: `experiments/protocol.yaml`. Harness: `experiments/harness.py`. Run records: `experiments/schemas/run.schema.json`.

## The question

Does the full Pith workflow raise the proportion of users who obtain an accepted, usable application **and then
make a substantial change without maintainer repair**, compared with

- **prose**: ordinary prose-driven development (the task statement, an empty workspace, no acceptance procedure);
- **core-tests**: good infrastructure with conventional tests (a trusted core module, its unit tests and example
  tests of the HTTP contract the agent may extend);
- **pith**: the full workflow (the pack's release, `AGENT.md`, the pinned judge, task packets, the migration check).

Core-tests separates the benefit of starting from good infrastructure from the additional benefit of independent
behavioural obligations and evidence.

## Scoring that does not favour Pith

Every condition is scored by the same external criteria (`experiments/external/counters_check.py`): a black-box
HTTP check that starts the subject's service with the command the subject declares in `run.json`, knows nothing of
Pith's layout, packs or judge, and at the change stage drives a populated version 1 state, produced by the
subject's **own** previous service, through the subject's own migration. A baseline is never failed for lacking
Pith's repository structure. The condition's own acceptance (none, the conventional tests, or the judge) is recorded
next to the external result, which is how false acceptance and false rejection are measured.

## Tasks

Each task is a build followed by a substantial change. The first task family, `counters`, is a bounded tally
service (build) and then named counters with the migration of a deployed, populated version 1 (change):
`experiments/tasks/counters/`. It is small on purpose so that runs are cheap enough to repeat. More families are
needed (the booking and approval packs are the obvious next two) before any result generalises.

## Design

- Full crossing: every model × task × condition × repeat is run (`repeats: 3` by default). Within each cell the
  order of the three conditions is rotated, so no condition always runs first.
- The budget (turns, wall clock, cost) is the same for every condition and recorded per run; exceeding it ends the run
  as abandoned, which counts as a failure.
- Each run records the exact model identifier the provider served, the harness, usage, every attempt, every
  intervention (who, what, and why the instructions were not enough), every setup failure, the workspace digest and
  the transcript digest.

## Outcomes

Primary: **accepted, usable, and changed without maintainer repair**: every external build criterion, then every
external change criterion (including regressions of the build criteria and the migration of populated state), with
no maintainer intervention at either stage. The analysis recomputes it from the stages; a record's own summary is
never trusted. Reported per condition and per model × condition, with Wilson 95% intervals.

Supporting: semantic regressions, false acceptance, false rejection, interventions, setup failures, repair cycles,
agent usage, evaluation cost, and the pack's authoring and maintenance cost (Pith's economic claim is that expert
work is amortised across applications and changes, not that formalisation is free).

## Running it

```bash
python3 experiments/harness.py plan --models <exact model ids> --out runs/plan.json   # the run list
# for each planned run: give the agent the condition's materials, let it work within the budget, then score it:
python3 experiments/external/counters_check.py --workspace WS --stage build --json
python3 experiments/external/counters_check.py --workspace WS2 --stage change --previous WS --json
# write runs/<run_id>.json (the schema), failures and abandoned runs included, then:
python3 experiments/harness.py validate runs/*.json
python3 experiments/harness.py analyze runs --plan runs/plan.json
```

`python3 experiments/harness.py dryrun OUT` runs the whole pipeline with two scripted agents in place of models
(`scripted:careful` submits correct work; `scripted:naive` first submits a migration that drops refused requests).
Its numbers measure the harness and nothing else; the analysis says so. CI runs it (`validation/governance.py`).

## Publication rules

Every planned run is published, including failed, abandoned and excluded ones, with the reason for any exclusion.
Transcripts are kept and released where participants agree. A holdout of the external criteria, maintained by
someone outside the pack's maintainers, is to supplement the visible criteria; it does not exist yet.

## Status (v0.13.0)

**No experiment with real models has been run.** (`evolution/handoff` records one handoff done by model agents; it is a
validation record of one run, not this experiment: one task, no conditions, no repeats.) The protocol, the task family, the external criteria, the run
record format, planning, validation, analysis and the scripted dry run exist and are tested in CI. Running it needs
model access and budget, and its results need publishing with the failures; that is the M6 exit criterion this
release does not meet. Since v0.13.0 a repair loop can be driven from the distilled packet alone (`experiments/harness.py
feedback`; docs/rfc/0007 § 5), and the dry run's scripted agents do; that is still the harness tested, not an experiment.
