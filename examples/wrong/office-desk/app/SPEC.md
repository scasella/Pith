# Office Desk — ring 3 application specification

This specification names the required workflows W1–W6 and evaluations E1–E3 from
obligations/app/delivery.yaml. Structural checks are reported by
obligations/app/lint.py; they are not semantic review.

## Requirements

- OC-1 (W1) The operator can create an account. Office Desk calls POST /accounts and displays the limit, posted, and available values returned by the service [INV1].
- OC-2 (W2, W3) The operator can submit an authorization request. Office Desk displays the decision returned by the service; the decision is the core's [P0] [P1].
- OC-3 (W4) The operator can release a live hold. Office Desk calls POST /accounts/{id}/release; hold removal and the request's terminal state are [R1] [R2].
- OC-4 (W5) Office Desk shows the event stream returned by GET /events for the selected account.
- OC-8 (W6) The operator can capture a live hold. Office Desk calls POST /accounts/{id}/capture; the posted amount, removed hold, and terminal request state are the posting kernel's [C1] [C2] [C3].
- OC-5 informal: (E1) An analyst can use the compact account and authorization forms, live holds table, and event stream. Evaluation: an analyst completes W1–W4 unassisted in under 3 minutes.
- OC-6 informal: (E2) Authorized and declined decisions use distinct color treatments. Evaluation: design review.
- OC-7 informal: (E3) User-facing copy uses the glossary's terms, including authorization request, available limit, decline, hold, and release. Evaluation: copy review against kernel/glossary.yaml.
- OC-9 informal: (E1) The account and authorization forms submit from the keyboard with Enter; tab order follows the visible controls, focus is visible, and a replay receipt is labeled as a replay while retaining the service's decision. Evaluation: keyboard walkthrough at desktop and mobile sizes.

The layout supports 1280×800 and 390×844 viewports (informal: E1).

## Human evaluation record

| Item | Evaluated by | Date | Result |
|---|---|---|---|
| E1 | (pending) | | |
| E2 | (pending) | | |
| E3 | (pending) | | |
