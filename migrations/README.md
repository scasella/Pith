# Migrations of the reservation pack

## Upgrading from authorization-and-posting-core/v2

Version 3 of the contract (`authorization-and-posting/v3`, pack 0.12.0) adds one behaviour and changes no proven
kernel: **every write answers with its receipt, and a retry returns that receipt** (record `Receipts`). Version 2
already did this for authorizations. For releases and captures it did not: a client whose release response was lost
and who retried was told `{released: false}`, which reads as "nothing was released" although the hold was gone, and a
retried capture came back without its amount. A receipt that a retry contradicts is the service-side version of the
interface defects the interaction obligations (I4, I5) exist for.

What changes for a client:

| Request | Version 2 answered | Version 3 answers |
|---|---|---|
| release, live hold | `{request_id, released: true}` | `{request_id, released: true, replayed: false}` |
| release, retried after it succeeded | `{request_id, released: false}` | `{request_id, released: true, replayed: true}` |
| release, never held or posted | `{request_id, released: false}` | `{request_id, released: false, replayed: false}` |
| capture, retried after it succeeded | `{request_id, captured: true, replayed: true}` | `{request_id, captured: true, amount, replayed: true}` |
| capture, nothing to capture | `{request_id, captured: false}` | `{request_id, captured: false, replayed: false}` |

The generated interface (`obligations/boundary/generate.py`) now has `ReleaseResponse` and requires `replayed` in every
write's response, so a candidate regenerates `gen/out` (the judge's `gen.current` check says so).

A running version 2 deployment is upgraded with its state, not started afresh (`MIG1`, `from-v2.yaml`, judged by
`gate/migrate.py`): every account, hold, status and event is kept byte for byte, and each acknowledged write becomes
its receipt, read from the event log, which is where version 2 kept them. The shipped profile ships the migration
(`profiles/sqlite/migrate.py`; a candidate on it calls `migrate(path)` from `service/migrate.py`) and refuses to open
state that was not migrated, so an old retry can never miss its receipt. A custom profile writes its own migration
and is judged the same way, black-box.

Rollback is forward-only: version 3 refuses state without receipts, and a version 2 service would write none.

`from-v2.yaml` states the mapping, how old retries and in-flight requests behave, and the rollback policy;
`populate.py` drives the old artifact's own service to produce the state (decisions both ways, request ids shared by
two accounts, a release and a capture each retried, a request in flight at SIGKILL, writes after the restart);
`verify.py` judges the new service on the migrated state.
