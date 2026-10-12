# <Application name> — ring 3 prose spec

Reviewed by humans. Two rules, checked structurally by `obligations/app/lint.py` (which is a lint, not a
semantic evaluator): (1) no sentence claims an authorization behavior without citing the obligation that
owns it: `[P0]` `[P1]` `[P2]` `[P3]` `[INV1]` `[R1]` `[R2]`; (2) everything else is `informal:` with the
human evaluation named. Required workflow ids (W1–W5) and evaluation ids (E1–E3) come from
`obligations/app/delivery.yaml`.

## Requirements

- OC-1 (W1) When an operator creates an account ... 
- OC-2 (W2, W3) When an operator submits an authorization, the application shall display the decision returned
  by the service. The decision is the core's [P0] [P1]; the application computes nothing.
- OC-3 (W4) ... hold removal is [R1] [R2].
- OC-4 (W5) The application shall show the event stream the monitor reads.
- OC-5 informal: (E1) usable by a payments-ops analyst without training. Evaluation: task completion under 3 minutes.
- OC-6 informal: (E2) declined decisions are visually distinct. Evaluation: design review.
- OC-7 informal: (E3) copy uses the glossary's words. Evaluation: copy review against kernel/glossary.yaml.

## Human evaluation record

| Item | Evaluated by | Date | Result |
|---|---|---|---|
| E1 | (pending) | | |
| E2 | (pending) | | |
| E3 | (pending) | | |
