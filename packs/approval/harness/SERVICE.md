# The approval service contract (pith.approval)

Frozen. The candidate owns `service/`, `cli/` and `app.manifest.yaml` and implements the whole workflow itself: this
pack ships no core. The service is judged black-box, over HTTP, against `harness/reference.py`, which
`harness/refines.py` shows equal to the TLA+ spec `model/Approval.tla` within the model's bounds.

## Starting

| `runtime` | Service the judge starts | CLI the judge runs (`delivery/CLI-CONTRACT.md`) |
|---|---|---|
| `python` | `python -I service/run.py --port <port> --db <path>` | `python -I cli/main.py ...` |
| `node` | `node service/run.mjs --port <port> --db <path>` | `node cli/main.mjs ...` |

The service listens on `127.0.0.1:<port>`, keeps all state under the directory of `<path>`, exits on SIGTERM, and
survives SIGKILL at any point: whatever it acknowledged is there after a restart.

## The actor model is simulated

Actors and their roles are registered through the API and named in each command (`actor`). The contract is about
what an actor with given roles may do; establishing who a caller really is (sessions, tokens, an identity
provider) is **not** part of it. An unregistered actor has no roles.

Roles: `editor` (creates documents and writes revisions), `approver` (approves or rejects), `publisher` (publishes).
The quorum is **two** distinct approvers for the current revision.

## The workflow

A document has revisions 1, 2, ... (each with its author and body), a status (`draft`, `in_review`, `approved`,
`rejected`, `published`), and the approvals ever recorded, each bound to the revision it approved.

| Command | Allowed when | Effect |
|---|---|---|
| create | the actor is an editor | revision 1 by the actor, `draft` |
| edit | the actor is an editor; not `published` | a new revision by the actor; `draft` (review starts over; earlier approvals stay in the history and never count again) |
| submit `revision` | `revision` is current; `draft`; the actor wrote the current revision | `in_review` |
| approve `revision` | approver; `revision` is current; `in_review`; the actor did not write it; has not approved it yet | the approval is recorded; `approved` when the current revision has two |
| reject `revision` | approver; `revision` is current; `in_review`; the actor did not write it | `rejected` |
| publish `revision` | publisher; `revision` is current; `approved` | `published`, which is final |

### Refusals

A command that is not allowed is **refused**: `200` with `outcome: "REFUSED"` and the first `reason` that applies,
in this order: `ROLE` (the actor lacks the role), `STALE_REVISION` (the command names a revision that is not current),
`WRONG_STATE`, `NOT_AUTHOR` (submit by someone other than the current revision's author), `SEPARATION_OF_DUTIES`
(approve or reject by the current revision's author), `ALREADY_APPROVED`. A refusal changes nothing, is recorded,
and is replayed like any other result. (`edit` names no revision; `create` can only be refused for `ROLE`.)

## Endpoints

| Method and path | Body | Success |
|---|---|---|
| `POST /actors` | `{id, roles}` | `201 {id, roles}`; duplicate `409` |
| `GET /actors` | | `200 {actors: [{id, roles}]}` |
| `POST /documents` | `{request_id, id, actor, title, body}` | `200 {request_id, outcome, reason, document, replayed}`; a document id in use `409` |
| `POST /documents/{id}/{edit,submit,approve,reject,publish}` | `{request_id, actor, body}` for edit; `{request_id, actor, revision}` otherwise | `200 {request_id, outcome, reason, document, replayed}`; unknown document `404` |
| `GET /documents/{id}` | | `200` the document view |
| `GET /events?since=N` | | `200 [{seq, type, ...}]`: each command's events, then one `op.committed` |

`document` (and `GET /documents/{id}`) is `{id, title, status, revision, revisions: [{revision, author, body}],
approvals: [{revision, actor}], current_votes: [actor]}` with approvals sorted by revision then actor and
`current_votes` sorted; it is `null` in the result of a refused create. Ids of actors and documents match
`^[a-z0-9][a-z0-9-]{0,63}$`; `request_id` and `revision` are JSON integers in `[0, 2^53)`; `title` and `body` are
strings of at most 10 000 characters. Anything else is `400` and changes nothing. `request_id` is the idempotency
key of every command (one namespace): a repeat returns the recorded result with `replayed: true`; a reuse for a
different command or parameters is `409`.
