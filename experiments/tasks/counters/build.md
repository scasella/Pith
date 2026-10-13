# Task: a bounded tally service (build stage)

Build an HTTP service, in any language and with any storage, that keeps a tally with a bound of 3.

- `POST /requests` with `{"request_id": <integer in [0, 2^53)>}` accepts the request (`"outcome": "OK"`) while the
  tally is below 3, and the tally grows by one; otherwise it answers `"outcome": "REFUSED"` and nothing changes. The
  answer is `{"request_id", "outcome", "tally", "replayed"}`.
- `request_id` identifies a request: sending it again returns the recorded answer with `"replayed": true` and changes
  nothing.
- `GET /tally` answers `{"tally", "bound": 3}`.
- Anything malformed is answered `400` and changes nothing.
- A result the service answered survives the process being killed at any moment and restarted.

Write `run.json` in your workspace: `{"start": "<command line with {port} and {db}>"}`; the service must listen on
`127.0.0.1:{port}` and keep its state at `{db}` (and beside it).
