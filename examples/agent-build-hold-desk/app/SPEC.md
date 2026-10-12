# Hold Desk — ring 3 prose spec

Reviewed by humans. The proof and black-box obligations own authorization behaviour. This document describes the operator workflows and evaluation criteria.

## Requirements

- OC-1 (W1) An operator creates an account with a limit; this workflow makes no authorization decision. [F]
- OC-2 (W2, W3) An operator submits an authorization request and sees the decision returned by the service. The application reports the core result under [P0] and [P1].
- OC-3 (W4) An operator releases a live hold and sees the available amount returned by the service. Hold removal follows [R1] and terminal request status follows [R2].
- OC-4 (W5) An operator views the event stream returned by the service in commit order.
- OC-5 informal: (E1) A payments-ops analyst can complete W1–W4 without training. Evaluation: task completion under 3 minutes.
- OC-6 informal: (E2) Declined decisions are visually distinct from authorized decisions. Evaluation: design review.
- OC-7 informal: (E3) User-facing copy uses the glossary's words. Evaluation: copy review against kernel/glossary.yaml.

## Human evaluation record

| Item | Evaluated by | Date | Result |
|---|---|---|---|
| E1 | (pending) | | |
| E2 | (pending) | | |
| E3 | (pending) | | |
