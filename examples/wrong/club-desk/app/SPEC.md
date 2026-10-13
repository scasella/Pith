# Club Desk — ring 3 prose spec

Reviewed by humans. Structural rules checked by `obligations/app/lint.py` (a lint, not a semantic evaluator):
no sentence claims an authorization behavior without citing the obligation that owns it: `[P0]` `[P1]` `[P2]` `[P3]` `[P4]` `[INV1]` `[R1]` `[R2]` `[C1]` `[C2]` `[C3]`; everything else is `informal:` with the human evaluation named. Required workflow ids W1–W6 and evaluation ids E1–E3 come from `obligations/app/delivery.yaml`.

## Requirements

- OC-1 (W1) When a club treasurer creates an account with a limit, Club Desk shall call `POST /accounts` and show limit, posted and available as returned by the service [INV1]; it computes nothing.
- OC-2 (W2, W3) When a club treasurer submits an authorization, Club Desk shall call `POST /accounts/{id}/authorize` and display the returned decision verbatim. The decision is the core's [P0] [P1]. A replay receipt shall be identified as a replay, not as a new decision [P3].
- OC-3 (W4) When a club treasurer releases a hold, Club Desk shall call `POST /accounts/{id}/release` and refresh; hold removal is [R1] [R2].
- OC-4 (W5) Club Desk shall show the event stream returned by the service so a treasurer can see the event types the monitor reads.
- OC-8 (W6) When a club treasurer captures a live hold, Club Desk shall call `POST /accounts/{id}/capture` and refresh; the posted amount and the removed hold are the posting kernel's [C1] [C2] [C3]; Club Desk computes nothing.
- OC-5 informal: (E1) usable by a first-time club treasurer without a separate tutorial. Evaluation: a treasurer completes W1–W4 in under 3 minutes.
- OC-6 informal: (E2) declined decisions are visually distinct from authorized ones. Evaluation: design review.
- OC-7 informal: (E3) copy uses the glossary's words (authorize, decline, hold, release) and no synonyms. Evaluation: copy review against `kernel/glossary.yaml`.
- OC-9 informal: the interface is a simulated club-budget tool using integer demonstration units; it is not banking software.

## Human evaluation record

| Item | Evaluated by | Date | Result |
|---|---|---|---|
| E1 | (pending) | | |
| E2 | (pending) | | |
| E3 | (pending) | | |
