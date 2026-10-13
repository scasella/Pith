# UI contract — affordances, not layout

The browser harness (`obligations/app/browser_workflows.py`) drives the application through these
`data-testid` bindings. Layout, framework, styling, copy, navigation and extra views are free. The ids must
exist and behave as described; where and how they are drawn is the application's choice.

| data-testid | Element | Behaviour |
|---|---|---|
| `acct-id` | input | account id (integer): a *draft* selection. Create and load read it; nothing else may target an account through it |
| `btn-load` | button | loads the account in `acct-id` via `GET /accounts/{id}`; only a successful response changes the loaded account |
| `loaded-account` | any | carries `data-account-id` = the account whose numbers and holds are displayed (from the response that produced them) and `data-state="current\|stale"`: `stale` once a refresh of that account has failed and the shown figures may be out of date |
| `acct-limit` | input | limit for account creation |
| `btn-create` | button | creates the account via `POST /accounts` |
| `available` | any | shows the account's current available amount as returned by the service (text contains the integer) |
| `req-id` | input | request id for the next authorization |
| `req-amount` | input | amount for the next authorization |
| `btn-authorize` | button | submits `POST /accounts/{id}/authorize` |
| `decision` | any | shows the outcome of the last authorization; carries `data-decision`, `data-account-id` and `data-request-id` (the operation's own identity). `data-decision` is `AUTHORIZED` or `DECLINED` when the service returned a decision (shown verbatim; the two must render with different computed colour — E2 is still a human review, this is the mechanical minimum), `REJECTED` when the service refused the request (4xx: nothing was decided), `UNKNOWN` when no response was received (5xx or network failure: the operation may or may not have committed; retry with the same request id). Empty or `NONE` when nothing is shown |
| `hold-row` | one per live hold | carries `data-request-id` and `data-account-id` (from the response that produced the row); contains a `btn-release` and a `btn-capture` |
| `btn-release` | button inside `hold-row` | submits `POST /accounts/{data-account-id}/release` for that row's hold |
| `btn-capture` | button inside `hold-row` | submits `POST /accounts/{data-account-id}/capture` for that row's hold (posting kernel) |
| `posted` | any | shows the account's posted amount as returned by the service |
| `events` | any | contains the event stream text (at least the types of the last events) |

Rules: every protected number shown comes from the API (never computed locally); a retry receipt is shown as a
replay, never as a new decision; the page must work at 1280×800 and 390×844.

## Interaction obligations

The proven core establishes that every operation the service performs is valid. It says nothing about whether the
operation the page submits is the one the user selected, or whether what the page shows is what happened. These
obligations pin down that mapping in observable terms. They are judged in a real browser through a judge-owned
proxy that delays, fails or loses chosen responses (`obligations/app/faultproxy.py`); every other request reaches
the real service, and every verdict is read from the service's own state.

| id | name | Rule |
|---|---|---|
| I1 | action-target binding | An action on a displayed hold targets that hold's account and request — never an account typed but not loaded. Accounts share request ids, so a request id alone identifies nothing |
| I2 | failed switch | If loading another account fails, the displayed holds remain bound to their own account (or are withdrawn); no action reaches the account that failed to load |
| I3 | view consistency | The loaded identity and the displayed state change together; a late response for a superseded selection never overwrites a newer one |
| I4 | receipt preservation | A received decision is never erased or contradicted by a later refresh failure; the figures it could not refresh are marked `stale`, and a later successful load restores `current` |
| I5 | outcome/view separation | "No response" (`UNKNOWN`), "the service refused" (`REJECTED`) and a decision are distinct; a same-id retry after `UNKNOWN` shows the receipt |
| I6 | receipt scope | A receipt keeps its originating account and request; after a switch it is either cleared or still names its account |

These concern observable action semantics, not the user's private intention. Disabling an action is always a
legitimate way to satisfy them; the judge reads effects, not buttons. `obligations/app/lib/pith-view.js` is an
optional, framework-free state module (draft selection, loaded view, pending operation, receipt) whose transitions
satisfy these rules by construction; using it is not required.
