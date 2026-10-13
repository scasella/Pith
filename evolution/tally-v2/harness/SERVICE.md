# The tally service contract, version 2

Frozen once sealed. The candidate owns `service/` and `app.manifest.yaml`. The judge starts
`python -I service/run.py --port <port> --db <path>`; the service listens on `127.0.0.1:<port>`, keeps its state under
the directory of `<path>`, exits on SIGTERM, and survives SIGKILL at any point: whatever it acknowledged is there after
a restart.

| Method and path | Body | Answer |
|---|---|---|
| `POST /requests` | `{"request_id": <integer in [0, 2^53)>, "counter": <name, optional>}` | `200 {"request_id", "counter", "outcome": "OK" or "REFUSED", "tally", "replayed"}` |
| `GET /tally?counter=<name>` | | `200 {"counter", "tally", "bound": 3}` |

A counter name is 1 to 32 characters of `a-z`, `0-9` and `-`; an absent `counter` means `default` (so a version 1
client keeps working against counter `default`). A request is accepted (`OK`) while its counter's tally is below the
bound 3, and that tally grows by one; otherwise it is `REFUSED` and nothing changes. `request_id` is the idempotency
key across all counters: a repeat returns the recorded result, with the counter it was recorded for and
`replayed: true`, whatever counter the repeat names, and changes nothing. Anything else is `400` and changes nothing.

## Upgrading from version 1

The judge stops the version 1 service, runs `python -I service/migrate.py --db <path>` once on the state directory it
left, then starts this version's service on the same `<path>`. After that (`migrations/from-1.yaml`):

- every result version 1 recorded is a result of counter `default`, same `request_id`, same outcome; version 1's tally
  is counter `default`'s tally;
- a repeat of a version 1 `request_id` returns that recorded result with `replayed: true`, never a new decision;
- a request that was in flight when version 1 stopped is decided at most once;
- `migrate.py` refuses (non-zero exit, nothing changed) state it does not recognise as version 1 or 2, and running it on
  state it already migrated changes nothing.
