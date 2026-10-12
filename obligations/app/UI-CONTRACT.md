# UI contract — affordances, not layout

The browser harness (`obligations/app/browser_workflows.py`) drives the application through these
`data-testid` bindings. Layout, framework, styling, copy, navigation and extra views are free. The ids must
exist and behave as described; where and how they are drawn is the application's choice.

| data-testid | Element | Behaviour |
|---|---|---|
| `acct-id` | input | account id (integer) used by every other action |
| `acct-limit` | input | limit for account creation |
| `btn-create` | button | creates the account via `POST /accounts` |
| `available` | any | shows the account's current available amount as returned by the service (text contains the integer) |
| `req-id` | input | request id for the next authorization |
| `req-amount` | input | amount for the next authorization |
| `btn-authorize` | button | submits `POST /accounts/{id}/authorize` |
| `decision` | any | shows the last decision verbatim; carries `data-decision="AUTHORIZED|DECLINED"`; the two values must render with different computed colour (E2 is still a human review; this is the mechanical minimum) |
| `hold-row` | one per live hold | carries `data-request-id`; contains a `btn-release` |
| `btn-release` | button inside `hold-row` | submits `POST /accounts/{id}/release` for that hold |
| `btn-capture` | button inside `hold-row` | submits `POST /accounts/{id}/capture` for that hold (posting kernel) |
| `posted` | any | shows the account's posted amount as returned by the service |
| `events` | any | contains the event stream text (at least the types of the last events) |

Rules: every protected number shown comes from the API (never computed locally); a retry receipt is shown as a
replay, never as a new decision; the page must work at 1280×800 and 390×844.
