# The approval CLI contract (pith.approval)

Frozen. Application delivery for this pack is a **command-line client**, not a page: the people who write, review and
publish policy documents run it from a terminal or a script. The candidate owns `cli/`. The judge runs it as the
candidate's user, against the candidate's running service (directly, through a judge-controlled proxy that injects
faults, or against an address where nothing listens), and judges each run by its exit code, its output and the
service's own state read with the frozen client (`harness/client.py`). The CLI talks to the service only over the
HTTP API of `harness/SERVICE.md`.

## Invocation

| `runtime` | Command |
|---|---|
| `python` | `python -I cli/main.py OPTIONS COMMAND DOC [ARGS]` |
| `node` | `node cli/main.mjs OPTIONS COMMAND DOC [ARGS]` |

Options (before the command): `--server URL` (required), `--actor ID` (required for every command but `show`),
`--request-id N` (optional), `--json` (optional).

| Command | Arguments | API call |
|---|---|---|
| `create DOC` | `--title T --body B` | `POST /documents` |
| `edit DOC` | `--body B` | `POST /documents/DOC/edit` |
| `submit DOC`, `approve DOC`, `reject DOC`, `publish DOC` | `--revision N` | `POST /documents/DOC/<command>` |
| `show DOC` | | `GET /documents/DOC` |

Every command but `show` sends exactly one request id: the `--request-id` given, or else one the CLI generates,
fresh for every run (two runs never share a generated id). The CLI never retries on its own.

## Outcomes and exit codes

| Exit | Outcome | When |
|---|---|---|
| `0` | `OK` | the service answered `200` with `outcome: "OK"` (a replay included), or `show` found the document |
| `3` | `REFUSED` | the service answered `200` with `outcome: "REFUSED"`: the workflow said no, for `reason` |
| `4` | `UNKNOWN` | no answer: the connection failed, was cut, or timed out. The command **may have been applied** |
| `5` | `ERROR` | the service answered with an error status (`400`, `404`, `409`, `5xx`): nothing was decided |
| `2` | | usage error (a missing or malformed option); nothing was sent |

A refusal, an error and an unknown outcome are three different things, and the CLI never reports one as another.
After `UNKNOWN`, the only safe next step is to run the same command again with the same `--request-id`: the
service replays the recorded result if the first attempt was applied, and applies it once if not.

## Output

With `--json`, stdout is exactly one JSON object:
`{"outcome": "OK"|"REFUSED"|"UNKNOWN"|"ERROR", "reason": string|null, "request_id": integer|null, "replayed": boolean|null, "document": <document view>|null}`
where `reason` is the service's refusal reason for `REFUSED` and a short description for `UNKNOWN` and `ERROR`, and
`document` is the service's document view when it sent one (after `UNKNOWN`, `null`: the CLI does not guess).

Without `--json`, the output is for a person. Its first line begins with the outcome word, and for `REFUSED` the
reason right after it (`REFUSED SEPARATION_OF_DUTIES`). Every command but `show` names the request id it sent as
`request <N>`; after `UNKNOWN` the output includes the exact retry option `--request-id <N>`. When a document is
shown, its lines include `status: <status>` and `revision: <n>`.

## Interaction obligations (judged with faults the judge injects)

- **AI1 — lost response.** The proxy forwards a command, the service commits it, and the proxy closes the connection
  without the answer. The CLI exits `4` with `UNKNOWN` and the request id; running it again with that
  `--request-id` exits `0` with `replayed: true`, and the service shows the command applied exactly once.
- **AI2 — unreachable service.** Nothing listens at `--server`. Every command exits `4`, never `0`, `3` or `5`.
- **AI3 — fresh request ids.** Runs without `--request-id` never share one: two different approvers approving
  through the CLI are both recorded.
