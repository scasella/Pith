# The tally service contract, version 1

Frozen once sealed. The candidate owns `service/` and `app.manifest.yaml`. The judge starts
`python -I service/run.py --port <port> --db <path>`; the service listens on `127.0.0.1:<port>`, keeps its state under
the directory of `<path>`, exits on SIGTERM, and survives SIGKILL at any point: whatever it acknowledged is there after
a restart.

| Method and path | Body | Answer |
|---|---|---|
| `POST /requests` | `{"request_id": <integer in [0, 2^53)>}` | `200 {"request_id", "outcome": "OK" or "REFUSED", "tally", "replayed"}` |
| `GET /tally` | | `200 {"tally", "bound": 3}` |

A request is accepted (`OK`) while the tally is below the bound 3, and the tally grows by one; otherwise it is
`REFUSED` and nothing changes. `request_id` is the idempotency key: a repeat returns the recorded result with
`replayed: true` and changes nothing. Anything else is `400` and changes nothing.
