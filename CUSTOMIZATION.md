# CUSTOMIZATION.md — what may vary, and what each kind of variation owes

The acceptance rule: *for the selected configuration, the application's protected observable
behaviour must conform to the selected specification.* Protected observations are decisions,
reservations, releases, externally visible balances, and durable commit outcomes. Everything else
may differ freely.

| Category | Examples | What it owes |
|---|---|---|
| **Presentation** (unrestricted) | layout, visual design, copy, navigation, device targets | product acceptance (`app/acceptance.py` demonstrates the required workflows) and the human evaluations in `obligations/app/delivery.yaml` |
| **Supported integration profiles** | persistence backend, concurrency strategy, deployment arrangement, client framework | `profile: custom`; never imported by the judge; must pass `obligations/service/lifecycle.py` and the boundary harness black-box through its service. The shipped `sqlite` profile is the reference; no profile inherits assurance from another |
| **Behavioural extensions** | new authorization policies (fraud, velocity), partial capture, refunds, expiry, limit changes, multi-currency | a spec change (`INTENT.md` § How a behavioural change is made) with new obligations, adequacy candidates and evidence; never implemented around the core |

Two consequences worth stating plainly. A fraud rule that declines some affordable requests
contradicts `P0`; building it in ring 3 while ring 0 still claims `P0` is a mis-statement the lint
can flag but only a human can judge, which is why ring 3 has `human_approval`. And a different
database is not "just the adapter": it is the mechanism that makes the proof's atomicity assumption
true, which is why a custom profile is judged by the frozen harness rather than by its author.

Boundaries the agent must not cross, whatever the category: compute a decision or an availability
figure outside the core and adapter; define a core type by hand anywhere; touch core state except
through the adapter.
