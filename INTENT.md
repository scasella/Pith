# INTENT.md — what the core means, what it excludes, how to change it

Reviewed prose. Not an oracle: nothing here is checked by a machine. It exists because formal
obligations determine conformance but cannot tell a reader what was intended, what was left out,
or how to change behaviour legitimately. (See `kernel/glossary.yaml` for the atom bindings.)

## The requirement, in words

When an authorization request exceeds the account's available limit, the system declines it and
reserves nothing. Requests within the limit, equality included, are authorized and a hold for the
exact amount is reserved. A hold exists only while its request is Authorized; releasing a hold frees
the funds and is terminal for that request. Declined is terminal. Posted plus reserved never exceeds
the limit. Each decision is made against the availability of the same atomic step.

## Deliberate decisions (and where each is enforced)

| Decision | Where |
|---|---|
| Equality authorizes (`amount <= available`) | `P0` in `kernel/spec/AuthSpec.dfy` |
| Availability is read in the decision step, never earlier | `DecideCorrect` in `obligations/design/CoreActions.tla`; `BEGIN IMMEDIATE` in the sqlite profile |
| Request id is the idempotency key; a replay never calls the core; a replay with a different amount is a conflict | lifecycle harness (black-box) |
| Amounts are integers in [1, 2^53); zero and negatives are invalid requests, not decisions; ids and limits in [0, 2^53) | `profiles/sqlite/core.py`; adapter and boundary harnesses |
| One account per `Account` value; one operation per atomic step; concurrency is a ring-1 (design) concern | ring structure |
| Settlement beyond posting (clearing, refunds, reversals) is out of scope | documented here; a behavioural extension |

## The second kernel: posting (v0.5.0)

Capture moves an authorized hold into `posted`, in full; the request becomes `Post`, which is terminal; a
posted request cannot be released and a second capture is a replay, not a second posting. Partial capture,
refunds and reversals are behavioural extensions. `INV1` is now shared: posting counts against the limit
exactly as a hold did, so available does not recover when a hold is captured.

| Decision | Where |
|---|---|
| Full capture only; posted grows by exactly the held amount | `C1`, `C2` in `kernel/spec/PostingSpec.dfy` |
| Post is terminal across every operation | `PostTerminal` lemmas; `P4` in `obligations/design/CoreActions.tla` |
| Posting never decreases | `PostedExact` (design obligations) |
| Capture is idempotent; a no-op when there is no hold and the request is not posted | lifecycle and boundary harnesses |

## What this core does not decide

Eligibility beyond the limit (fraud, velocity, merchant rules), currency, expiry of holds, partial
captures, settlement, and anything about users or interfaces. The core authorizes every affordable
request. If your product declines some affordable requests, that is a **behavioural extension**
(see `CUSTOMIZATION.md`), not an application feature: it changes `P0` or adds an explicit
eligibility precondition, and it needs its own obligations and evidence.

## How a behavioural change is made

1. Change `kernel/spec/AuthSpec.dfy` (or add a new core); re-prove `kernel/core`; update the adequacy
   suite with the wrong candidates the change must now reject; regenerate traces and have them signed.
2. Update `obligations/design/CoreActions.tla` so the design obligations match; keep the known-bad
   design and coverage checks meaningful.
3. Regenerate ring-2 artifacts; extend the monitor contract and its negative suite.
4. Re-freeze (`gate/frozen.sha256`), bump the seed version, and publish the new policy. Builds
   judged against the old policy keep their claims; they do not inherit new ones.

Agents do not do step 1–4. If an agent believes the obligations are wrong or unsatisfiable, it reports
that, or files a proof in `kernel/audit/`.
