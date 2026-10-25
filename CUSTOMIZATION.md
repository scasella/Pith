# CUSTOMIZATION.md — what may vary, and what each kind of variation owes

The acceptance rule: *for the selected configuration, the application's protected observable
behaviour must conform to the selected specification.* Protected observations are decisions,
reservations, releases, externally visible balances, and durable commit outcomes. Everything else
may differ freely.

| Category | Examples | What it owes |
|---|---|---|
| **Presentation** (unrestricted) | layout, visual design, copy, navigation, device targets, UI framework | the required workflows and interaction obligations in `obligations/app/delivery.yaml` (judged in the browser through `UI-CONTRACT.md`) and the human evaluations there. Presentation is free; the mapping from what is shown and selected to the operation submitted is not |
| **Supported integration profiles** | persistence backend, concurrency strategy, deployment arrangement, client framework | `profile: custom`; never imported by the judge; must pass `obligations/service/lifecycle.py` and the boundary harness black-box through its service. The shipped `sqlite` profile is the reference, and `sqlite-occ` (v0.13.0) a second shipped profile with optimistic concurrency, judged by its own tests; no profile inherits assurance from another |
| **Behavioural extensions** | new authorization policies (fraud, velocity), partial capture, refunds, expiry, limit changes, multi-currency | a spec change (`INTENT.md` § How a behavioural change is made) with new obligations, adequacy candidates and evidence; never implemented around the core |

The three categories are the three change routes every contract record names (`change` in `pack.yaml`), and
`pack.yaml: change_routes` maps the candidate's paths onto them. `python3 gate/cli.py change plan|classify` applies
them to a concrete change and says what must be re-established; it is advisory and flags ambiguity, because a
change's category is ultimately about intent (`docs/rfc/0004-safe-evolution.md` § 2).

Two consequences worth stating plainly. A fraud rule that declines some affordable requests
contradicts `P0`; building it in ring 3 while ring 0 still claims `P0` is a mis-statement the lint
can flag but only a human can judge, which is why ring 3 has `human_approval`. And a different
database is not "just the adapter": it is the mechanism that makes the proof's atomicity assumption
true, which is why a custom profile is judged by the frozen harness rather than by its author.

Boundaries the agent must not cross, whatever the category: compute a decision or an availability
figure outside the core and adapter; define a core type by hand anywhere; touch core state except
through the adapter.
