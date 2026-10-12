# Operator console — ring 3 prose spec

Reviewed by humans. Structural rules checked by `obligations/app/lint.py` (a lint, not a semantic evaluator):
no sentence claims an authorization behavior without citing the obligation that owns it; everything else is
`informal:` with the human evaluation named. Workflow ids W1–W6 and evaluation ids E1–E3 are from
`obligations/app/delivery.yaml`; `app/acceptance.py` demonstrates W1–W5 through the running service.

## Requirements

- OC-1 (W1) When an operator creates an account with a limit, the console shall call `POST /accounts` and show
  limit, posted and available as returned by the service [INV1]; it computes nothing.
- OC-2 (W2, W3) When an operator submits an authorization, the console shall call `POST /accounts/{id}/authorize`
  and display the returned decision verbatim. The decision is the core's [P0] [P1].
- OC-3 (W4) When an operator releases a hold, the console shall call `POST /accounts/{id}/release` and refresh;
  hold removal is [R1] [R2].
- OC-8 (W6) When an operator captures a live hold, the console shall call `POST /accounts/{id}/capture` and refresh; the
  posted amount and the removed hold are the posting kernel's [C1] [C2] [C3]; the console computes nothing.
- OC-4 (W5) The console shall show the event stream so an operator can see what the monitor sees.
- OC-5 informal: (E1) usable by a payments-ops analyst with no training. Evaluation: two analysts complete W1–W4 under 3 minutes.
- OC-6 informal: (E2) declined decisions are visually distinct from authorized ones. Evaluation: design review.
- OC-7 informal: (E3) copy uses the glossary's words (authorize, decline, hold, release) and no synonyms. Evaluation: copy review.

## Human evaluation record

| Item | Evaluated by | Date | Result |
|---|---|---|---|
| E1 | (pending) | | |
| E2 | (pending) | | |
| E3 | (pending) | | |
