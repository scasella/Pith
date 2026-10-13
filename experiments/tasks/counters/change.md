# Task: named counters, upgrading a running deployment (change stage)

Change the service you built so that it keeps one tally per named counter, each with its own bound of 3.

- `POST /requests` takes an optional `"counter"` (1 to 32 characters of `a-z`, `0-9`, `-`); without one the request
  counts against the counter `default`. The answer gains `"counter"`.
- `GET /tally?counter=<name>` answers `{"counter", "tally", "bound": 3}`; without `counter`, the counter `default`.
- `request_id` stays unique across counters: a repeat returns the recorded answer, with the counter it was recorded
  for, whatever counter the repeat names.

Your previous version is deployed and holds real data. Add `"migrate": "<command line with {db}>"` to `run.json`: it
is run once, with the service stopped, on the state your previous version left, before the new version starts on it.
Every request the previous version answered must still be answered the same way (as counter `default`), and the
tally it reached must still be reached. Do not assume the database is empty.
