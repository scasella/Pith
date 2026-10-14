# evolution/handoff — a handoff between two model agents (v0.12.0)

The handoff in `validation/evolution.py` uses scripted edits for both agents. This directory records the same handoff
done once by two model agents, on the `demo.tally` 2.0.0 release (`evolution/tally-v2`, release
`e7bf373c80b4a359a02e1242f1ffe76aee54f6c3c772c34b865c48d7c7c434b3`), on 2026-10-13. It is a validation record of one
run, not an experiment: one task, one pair of agents, no repeats, no comparison condition (`docs/EXPERIMENTS.md` is
where that is measured).

**Who.** Two sub-agents of a coding-agent harness, each started with a fresh context and only the prompt summarised
below; the maintainer did not intervene in either run. The model identifier is kept with the maintainer, not in this
repository. Neither agent could read this repository: each worked in a directory holding only the release (and, for B,
A's application and evidence).

**Agent A** was asked to build an application for the release from its frozen files alone, and to finish when the
judge accepts it. It wrote `agent-a/` (`service/run.py`, `service/store.py`, `service/migrate.py`,
`app.manifest.yaml`). One judge run, accepted (`recorded/agent-a-report.md`). It reported four things it found unclear
or wrong in the contract, all of them real:

1. `pack.yaml` names `INTENT.md` as its intent, but a release is `gate/`, `pack.yaml` and the policy dirs, so the file
   is not in the release a candidate receives;
2. the state a version 1 service leaves is not described anywhere in the release, so `migrate.py` has to recognise it
   by guessing (A's guess, by content, migrates the real version 1 state: `validation/handoff.py` step 1);
3. "anything else is 400" does not say whether extra body keys or query parameters count;
4. the `wrong:` paths in `pack.yaml` are not in the release.

**Agent B** took over A's workspace and A's accepted evidence and task packet, with the project's rule for changing an
accepted application (plan before, classify after, judge with `--reuse`, stop on a behavioral route) and a product
owner's two-part request: log every `POST /requests` as one JSON line on stderr, and let counter `vip` make 5 requests
instead of 3. B planned both (`recorded/plan-run.json`, `recorded/plan-vip.json`), made the first, classified it
(`recorded/classify.json`), and was judged once with A's evidence offered: accepted, the two model checks reused, the
three service checks run again. It refused the second as a contract change, and said why the route report did not
tell it so: routes are declared by path, so a bound change inside `service/` reads as an integration change, and the
frozen harness might not catch a counter named `vip`. That is the limit RFC 0004 § 9 states for the route report;
here a model agent recognised it on its own (`recorded/agent-b-report.md`).

**What is re-checked.** `python3 validation/handoff.py OUT` (CI job `packs`) runs no model. It judges what the agents
produced with the pristine releases and checks the record: A is accepted and migrates state the accepted tally 1
application produced; B's recorded plans and classification say what is written above; classifying B against A's
evidence today gives what B recorded; B judged with A's evidence offered is accepted, reusing only what holds; B
changed only `service/run.py`; and B's service still refuses counter `vip` at its fourth request.

**What this does not show.** How often agents do this; whether a smaller model would; anything about a pack other
than this small one. The contract findings above are recorded here and in `docs/rfc/0006-upgrading-the-main-packs.md`
§ 6; changing the tally releases to answer them is left to their maintainer, because they are demonstration releases
whose digests other records cite.
