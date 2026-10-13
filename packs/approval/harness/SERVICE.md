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
Each document has a **quorum**: how many distinct approvers (none of them the current revision's author) must
approve its current revision. The editor who creates the document chooses it (`quorum`, an integer from 2 to 5;
without it, 2). It is fixed at creation: no command changes it, and an edit does not reset it. [A3] [A9]

## The workflow

A document has revisions 1, 2, ... (each with its author and body), a status (`draft`, `in_review`, `approved`,
`rejected`, `published`), its quorum, and the approvals ever recorded, each bound to the revision it approved.

| Command | Allowed when | Effect |
|---|---|---|
| create `quorum` | the actor is an editor | revision 1 by the actor, `draft`, with that quorum (2 when not given) |
| edit | the actor is an editor; not `published` | a new revision by the actor; `draft` (review starts over; earlier approvals stay in the history and never count again) |
| submit `revision` | `revision` is current; `draft`; the actor wrote the current revision | `in_review` |
| approve `revision` | approver; `revision` is current; `in_review`; the actor did not write it; has not approved it yet | the approval is recorded; `approved` when the current revision has the document's quorum of them |
| reject `revision` | approver; `revision` is current; `in_review`; the actor did not write it | `rejected` |
| publish `revision` | publisher; `revision` is current; `approved` | `published`, which is final |

### Refusals

A command that is not allowed is **refused**: `200` with `outcome: "REFUSED"` and the first `reason` that applies,
in this order: `ROLE` (the actor lacks the role), `STALE_REVISION` (the command names a revision that is not current),
`WRONG_STATE`, `NOT_AUTHOR` (submit by someone other than the current revision's author), `SEPARATION_OF_DUTIES`
(approve or reject by the current revision's author), `ALREADY_APPROVED`. A refusal changes nothing, is recorded,
and is replayed like any other result. (`edit` names no revision; `create` can only be refused for `ROLE`.)

The order is a layering, from the caller outwards: who is asking (`ROLE`), which revision they mean
(`STALE_REVISION`), whether the document is in a state where the command means anything at all (`WRONG_STATE`),
and only then the rules about this actor and this revision (`NOT_AUTHOR`, `SEPARATION_OF_DUTIES`) and the vote
history (`ALREADY_APPROVED`). So the same self-approval is `WRONG_STATE` while the document is a draft and
`SEPARATION_OF_DUTIES` once it is in review: the first tells the caller the command cannot apply yet, the second
that it never will for them. `model/traces.yaml` T8 and T11 pin every adjacent pair.

## Endpoints

| Method and path | Body | Success |
|---|---|---|
| `POST /actors` | `{id, roles}` | `201 {id, roles}`; duplicate `409` |
| `GET /actors` | | `200 {actors: [{id, roles}]}` |
| `POST /documents` | `{request_id, id, actor, title, body, quorum}` (`quorum` optional) | `200 {request_id, outcome, reason, document, replayed}`; a document id in use `409` |
| `POST /documents/{id}/{edit,submit,approve,reject,publish}` | `{request_id, actor, body}` for edit; `{request_id, actor, revision}` otherwise | `200 {request_id, outcome, reason, document, replayed}`; unknown document `404` |
| `GET /documents/{id}` | | `200` the document view |
| `GET /events?since=N` | | `200 [{seq, type, ...}]`: each command's events, then one `op.committed` |

`document` (and `GET /documents/{id}`) is `{id, title, status, revision, quorum, revisions: [{revision, author, body}],
approvals: [{revision, actor}], current_votes: [actor]}` with approvals sorted by revision then actor and
`current_votes` sorted; it is `null` in the result of a refused create. Ids of actors and documents match
`^[a-z0-9][a-z0-9-]{0,63}$`; `request_id` and `revision` are JSON integers in `[0, 2^53)`; `title` and `body` are
strings of at most 10 000 characters; `quorum`, when given, is a JSON integer in `[2, 5]` (an explicit `null` is not
"not given"). Anything else is `400` and changes nothing. `request_id` is the idempotency
key of every command (one namespace): a repeat returns the recorded result with `replayed: true`; a reuse for a
different command or parameters is `409`. A create's parameters include its quorum, and a create without `quorum`
is the same command as one naming 2.

## Upgrading from version 1

Version 1 of this contract (`approval-workflow/v1`) fixed the quorum at two. A running version 1 service is upgraded
with its state (`migrations/from-v1.yaml`, contract record MIG1): the judge stops the version 1 service, runs the
candidate's migrate entrypoint on the state directory it left, then starts this version's service on the same
`--db <path>`.

| `runtime` | Migrate entrypoint |
|---|---|
| `python` | `python -I service/migrate.py --db <path>` |
| `node` | `node service/migrate.mjs --db <path>` |

`<path>` is the same `--db` path the service is started with. The entrypoint transforms the state in place. After it
(and the judge checks each, black-box, on state a version 1 service really produced):

- every version 1 document is a document with quorum 2, keeping its revisions (authors and bodies), its title, its
  status and every approval ever recorded, the approvals of superseded revisions included: they are history and
  never count again (A3, A7). Nothing is re-decided: an `approved` document stays approved, a document `in_review`
  with one approval needs one more;
- actors keep their roles; the event log keeps what it had;
- every command result version 1 recorded is kept: a version 1 client repeating a version 1 `request_id` with the
  same command gets that recorded result with `replayed: true` (its `document` now carries `quorum: 2`), never a new
  decision: an approval retried after the upgrade is a replay, not `ALREADY_APPROVED`. A version 1 create (it named
  no quorum) is the same command as a create naming 2. A reuse of an old `request_id` for anything else is `409`;
- a command that was in flight when version 1 stopped (it may or may not have been recorded) is decided at most once:
  replayed if version 1 recorded it, decided by this version otherwise, never both;
- the entrypoint refuses state it does not recognise as version 1 or version 2 (non-zero exit, nothing changed), and
  running it again on state it already migrated succeeds and changes nothing.

There is no way back: once a document is created with a quorum other than 2, version 1 cannot represent the state
(`migrations/from-v1.yaml` rollback: forward-only).
