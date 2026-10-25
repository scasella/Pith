# evolution/handoff/fork-join — a fork-join handoff, scripted (v0.13.0)

`../README.md` records two model agents working one after the other. This directory records the other shape of
handoff: several agents working **in parallel** from one accepted application, and a merge of what they made.

**The branches are scripted, not model agents.** Like the handoff in `validation/evolution.py`, each branch is a fixed
set of files written for this scenario; nobody ran a model, and nothing here measures how agents behave. The model-agent
run is the other record (`../README.md`, `docs/rfc/0006-upgrading-the-main-packs.md` § 6). What this one shows is what
the merge tooling (`gate/change.py merge`, `pith handoff merge`; `docs/rfc/0007-autonomous-assurance-and-runtime-composition.md`
§ 8) does with branches that do disjoint things, and with a pair that look disjoint and are not.

## The base and the branches

The base is `examples/build-a`, accepted by the reservation pack's release. Each branch is an overlay: a directory
holding only the files it changes relative to the base.

| Branch | Does | Files | Partitions (`pack.yaml: partitions`) |
|---|---|---|---|
| `agent-a/` | moves storage to the optimistic profile (`sqlite-occ`) | `app.manifest.yaml`, `service/app.py`, `service/run.py`, `service/migrate.py` (the files in which `examples/build-occ` differs from the base) | `integration`, `migration` |
| `agent-b/` | overhauls the page: it reads the bounds of the authorization amount from the service's own `/openapi.yaml`, and keeps every action disabled if it cannot | `ui/index.html` | `presentation` |
| `agent-c/` | trims the service to the API it must serve: it no longer serves `/openapi.yaml`, which nothing in the judge fetches and the base page never reads | `service/app.py` | `integration` |

Each branch is accepted alone by the pristine release, judged with the base's evidence offered: the proof and the model
checks are reused (their inputs did not change), everything that starts the service runs again.

## The three merges

`python3 gate/change.py merge --base-candidate examples/build-a --base <base evidence> --branch NAME=DIR:EVIDENCE ... --out MERGED
--judge EVIDENCE_OUT`: refuse a textual conflict, two branches in one partition, or a change to a boundary partition;
otherwise write the merged tree, say which evidence still holds for it, and run the judge on it with every evidence directory
offered. `recorded/` holds the three reports (`pith.merge-report/v1`) from one run, with the machine's paths replaced by `<run>`.

| Merge | Static | Judge on the merged tree | Merge |
|---|---|---|---|
| `agent-a` + `agent-b` (`recorded/merge-a-b.json`) | no conflict; partitions disjoint (`integration`+`migration` / `presentation`) | **accepted**. It reused exactly the cacheable records (the kernel proof and the nine model checks of the design) and ran every other check again, the lifecycle harness, the boundary harness and the browser workflows each starting the merged service | stands (exit 0) |
| `agent-b` + `agent-c` (`recorded/merge-b-c.json`) | no conflict; partitions disjoint (`presentation` / `integration`); the cacheable evidence still holds | **refused at delivery**, everything before it passing. It reused the same cacheable records | refused (exit 1) |
| `agent-a` + `agent-c` (`recorded/merge-a-c.json`) | **refused**: both branches changed the `integration` partition (and both rewrote `service/app.py`, reported as a textual conflict; the tool compares whole files and does not merge hunks) | not run | refused (exit 1) |

`expected.yaml` holds the two refusals, and `validation/judge_wrong.py --handoff` checks them for exactly their reason:
`agent-b` + `agent-c` is refused by the judge at `delivery`, and the workflows that fail are exactly `I1`–`I6` and the
browser harness's own `error` (its workflow run raised, so W1–W6 are absent rather than failed; every button on the merged
page stays disabled); `agent-a` + `agent-c` is refused statically, with the conflict on partition `integration` and nothing
else. A refusal for another reason (a missing browser, a different failing workflow) does not count.

## The shared assumption no contract states

`agent-b`'s page assumes **the service publishes `/openapi.yaml`**. `agent-c`'s service assumes nothing reads it. Each was
right about its own branch: the base page never fetched it, the judge never fetches it, and the pack's contract records
do not say that a service must publish it (the generated interface document is the *boundary's* artifact, in a boundary
partition no branch may touch; whether the running service serves it is the integration's choice). So the two branches
are disjoint (one is in `presentation`, the other in `integration`) and nothing in the declarations connects them. The
merged application fails anyway, and the only thing that can say so is running it.

## What disjoint partitions prove, and what they do not

Disjoint partitions prove **which evidence carries over**, never that the merged application works. For `a`+`b` and `b`+`c`
alike the merge report says, from the files each check read:

- the proof and the model checks read nothing either branch changed, so their results hold for the merged tree (`evidence.holds`,
  and the judge reuses them from the base's evidence: one run of each, not one per branch);
- every service-starting check a branch passed alone (`lifecycle`, `boundary`, `delivery`, ...) read files in the partition
  the **other** branch changed (the page is served by the service; the service serves the page), so its result does not carry
  over and is listed under `evidence.cross_partition`.

## Service-starting checks always run again

`ARCHITECTURE.md` and RFC 0001 make this a soundness rule, and the merge keeps it: a merged tree is a new artifact, and
only observing it says what it does. Only the proof and the model checks are cacheable (`--reuse`, including `--reuse`
given once per evidence directory); each check that starts the candidate's service runs on the merged tree whatever the
partitions say. That rule is what catches `agent-b` + `agent-c`: a merge tool that carried the browser workflows' results
over from the branches because the partitions were disjoint would have accepted it. Nothing in `merge` can do that, and
`validation/handoff.py` checks that the judge reused only the cacheable records, in both the accepted and the refused case.

## Re-checking, and re-recording

`python3 validation/handoff.py OUT` (CI job `packs`) runs no model. After its tally checks it judges the base and the three
branches, merges `a`+`b` with the judge, calls `validation/judge_wrong.py --handoff evolution/handoff/fork-join OUT/fork-join`
for the two refusals, and checks that the fresh reports agree with `recorded/` on every field that is not specific to the
machine, the run or the release digest: conflicts, partitions touched, which evidence holds and which re-runs, the
cross-partition results, the judge's verdict, first failure and reused checks. Everything is recorded in
`OUT/handoff-record.json`. The recorded reports were produced by `python3 validation/handoff.py OUT --record`; run it again,
and review the diff, when the pack's check ids change.

## What this does not show

How agents behave when they work in parallel; whether partitions this coarse suit a larger application (`pack.yaml`
declares five, and two branches may not share one: a finer partition is a pack change); anything about a pack other
than the reservation pack, which is the only one that declares partitions so far.
