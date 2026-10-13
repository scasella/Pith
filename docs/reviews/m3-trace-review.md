# Trace review: packs/booking and packs/approval

Reviewer: independent formalization review (branch `claude/m3-prove-generality-yxjpt4`). No repository file was modified.

Method. For every trace I first wrote down the outcome I expected from INTENT.md alone, then compared it with the trace.
I then checked each formal obligation against the INTENT sentence it cites. To find gaps I did not rely on reading:
I mutated copies of the oracle in the scratchpad and re-ran the pack's own checks.

- Booking: three mutants of `BookingSpec.dfy` (in `review/spec_{a,b,c}`), run with `dafny test` on `traces.dfy`.
- Approval: twelve mutants of `harness/reference.py` (in `review/approval_mut/*`), run with `harness/traces.py`.
- Approval: four of those mutants (in `review/refmut/*`), run with `harness/refines.py` against TLC.

Baseline: all 8 booking traces pass (`dafny test`: 8 verified, 8 PASSED). All 8 approval traces pass
(`{"traces": 8, "accepting": 2, "problems": {}}`). `refines.py` baseline: 1314 states, 1602 transitions, no problems.

---

## Pack 1: packs/booking — verdict: ACCEPT WITH CHANGES

As far as I can tell, `BookingSpec.dfy` says what INTENT.md says. The outcome cases of Book and Reschedule are
exhaustive and mutually exclusive:

- Book: Invalid ⇔ ¬WF; Accepted ⇔ WF∧Free; never NotActive; so Conflict ⇔ WF∧¬Free.
- Reschedule: NotActive ⇔ ¬active; Invalid ⇔ active∧¬WF; Accepted ⇔ active∧WF∧Free; so Conflict ⇔ active∧WF∧¬Free.

X1–X3 and M0–M3 are as strong as the prose. My hand-derived outcome matched the asserted one on all 8 traces.

Each trace comment says which wrong core it separates. I checked each claim by hand against the code in `spec/wrong/`, and all are correct:

| Trace | Wrong core | How the wrong core differs on this trace |
|---|---|---|
| T1 | closed_intervals | refuses the touching booking (`660 <= 660`) |
| T2 | conflict_names_requester | names `Conflict(3)` |
| T3 | start_inside_only | accepts 540–720 |
| T5 | cancel_toggles | the second cancel returns `false` but revives booking 1 (so `c3 != c2`) |
| T6 | reschedule_blocks_itself | conflicts with itself |
| T7 | reschedule_cancel_then_book | returns the calendar with booking 1 deactivated |

The problem is that the traces pin the boundary convention on one side only. Three spec mutants that contradict
INTENT.md pass every trace.

### B-1 (major). Half-open is checked only for "starts when another ends", not for "ends when another starts"

**Where.** `spec/traces.dfy:11-17` (T1), `spec/BookingSpec.dfy:18`.

**What is missing.** Mutant (a) changes Overlaps to `s1 <= e2 && s2 < e1`, which is closed at the requester's end.
It passes T1–T8, and it refuses `[540,600)` next to `[600,660)`, which INTENT.md [HALF-OPEN] says is free. In this
pack only `harness/lifecycle.py:37` would catch it, at the service level, and that is not a reviewed trace.

**Proposed trace.**

```dafny
method {:test} T9_TouchingFromBelowIsAccepted() {      // a spec closed at the requester's end refuses the second
  var k := new Core();
  var o1, c1 := k.Book([], 1, 600, 660);
  var o2, c2 := k.Book(c1, 2, 540, 600);                  // 09:00-10:00 ends exactly when 1 starts
  expect o1 == Accepted && o2 == Accepted && |c2| == 2;
}
```

Also add a wrong core `spec/wrong/closed_at_end.dfy`, using `c[k].start <= e && s < c[k].end`, so that the
asymmetric mistake has a named wrong core.

### B-2 (major). "One that starts a minute earlier does [conflict]" is stated in INTENT.md but covered nowhere

**Where.** `INTENT.md` [HALF-OPEN]; `spec/traces.dfy` T2 and T3 overlap by 30 minutes or more.

**What is missing.** Mutant (b) changes Overlaps to `s1 + 1 < e2 && s2 + 1 < e1`, which ignores one-minute overlaps.
It passes T1–T8. It also passes `harness/lifecycle.py`, because the smallest overlap there is 10 minutes. It also
passes `harness/conformance.py`, which compares the service with the core (so a spec change moves both) and uses only
multiples of 10. The one sentence in INTENT.md that gives a concrete minute case has no executable witness.

**Proposed trace.**

```dafny
method {:test} T10_OneMinuteOverlapConflicts() {
  var k := new Core();
  var _, c1 := k.Book([], 1, 600, 660);
  var o, c2 := k.Book(c1, 2, 659, 720);                   // starts one minute before 1 ends
  var p, c3 := k.Book(c1, 3, 540, 601);                   // ends one minute after 1 starts
  expect o == Conflict(1) && p == Conflict(1) && c2 == c1 && c3 == c1;
}
```

Optionally change `conformance.py`'s op strategy to use unscaled minutes, or mix in `±1` offsets. As written,
`s, e = a*10, b*10` can never produce a one-minute overlap.

### B-3 (medium). The shortest valid booking (one minute) is never exercised

**Where.** `spec/traces.dfy:34-39` (T4) checks only `end == start` and `end < start`.

**What is missing.** Mutant (c) changes WellFormed to `s + 1 < e`. It passes T1–T8, and no lifecycle step books a
one-minute interval either. INTENT.md [B1] makes exactly `end <= start` invalid, so `[600,601)` must be accepted.

**Proposed change.** Extend T4 with `var o3, c3 := k.Book([], 3, 600, 601); expect o3 == Accepted;`.

### B-4 (medium). Reschedule refusal paths other than Conflict, and their precedence, have no trace

**Where.** `spec/BookingSpec.dfy:64-65` ([M0] and [B1] for Reschedule).

**What is missing.** No trace moves an active booking to an empty or reversed interval (expected `Invalid`, calendar
unchanged). No trace moves an unknown id (expected `NotActive`). No trace pins the precedence NotActive > Invalid,
where a cancelled booking moved to `[700,700)` gives `NotActive`. That precedence is reasonable: "the target does
not exist" comes before "the arguments are bad". But it is a choice, and nothing shows it.

**Proposed trace.**

```dafny
method {:test} T11_MoveRefusalsAndTheirOrder() {
  var k := new Core();
  var _, c1 := k.Book([], 1, 600, 660);
  var o1, d1 := k.Reschedule(c1, 1, 700, 700);            // active, empty interval
  var o2, d2 := k.Reschedule(c1, 9, 700, 760);            // unknown id
  var _, c2 := k.Cancel(c1, 1);
  var o3, d3 := k.Reschedule(c2, 1, 700, 690);            // cancelled AND reversed: NotActive wins
  expect o1 == Invalid && d1 == c1 && o2 == NotActive && d2 == c1 && o3 == NotActive && d3 == c2;
}
```

### B-5 (minor). "Cancelling frees exactly that booking" [X2] has no trace with a second booking

**Where.** `spec/traces.dfy:41-49` (T5) has one booking only.

**What is missing.** A cancel that deactivates every booking on the resource would agree with T5. The spec [X2] is
strong enough, so this concerns the review artifact only: no concrete case shows "exactly".

**Proposed change.** Add booking 2 at `[660,720)` before the cancel in T5, and expect `c2[1].active` afterwards.
Also cancel an unknown id and expect `!ok && c' == c` ([X3], "unknown ids change nothing").

### B-6 (minor). Shifting within its own time is claimed but only shrinking is traced

**Where.** `INTENT.md` [M1] says "a booking can shrink **or shift** within itself"; T6 (`spec/traces.dfy:51-56`) only shrinks.

**Proposed change.** Add `Reschedule([Slot(1,600,660,true)], 1, 630, 690)` and expect `Accepted`. Optionally also
add a move that ends up touching a neighbour (1 to `[600,660)` next to 2 at `[660,720)`, expect `Accepted`), so M1
is checked with half-open semantics too.

### B-7 (minor, wording). INTENT.md says "day line"; the contract is unbounded

**Where.** `INTENT.md` ("minutes on one abstract, timezone-free day line"); `harness/api.schema.json:5` allows times up to 2^53−1.

**What is wrong.** "Day line" reads as `[0, 1440)`, but the spec uses `nat` and the API accepts much larger values.

**Proposed change.** Say "an abstract, timezone-free line of whole minutes (not bounded to one day)".

### Checked and fine

- B5 with several blockers: the spec allows any real blocker to be named. `lifecycle.py:38` accepts `(1, 2)`. Consistent with INTENT.md ("a booking that really is in the way").
- Book precondition `!Has(c, id)`: SERVICE.md:31 makes the booking id the book `request_id` in one global namespace, so the precondition is discharged by the service, and a refused book never enters the calendar.
- A booking over a cancelled interval is accepted (T5): correct.
- Rescheduling cannot change `active` (M2 updates only start and end): correct.
- Resource independence, idempotency and durability are not in the spec. They are honestly routed to `harness/lifecycle.py` (pack.yaml Independence, Idempotency, Durability), and `lifecycle.py:42` checks independence.

---

## Pack 2: packs/approval — verdict: ACCEPT WITH CHANGES (close to reject on A1/A2 coverage)

My hand-derived outcome matched the asserted one on every step of T1–T8. The three wrong designs are each separated
by the trace named in its comment, and I checked each by hand:

- WrongSelfApproval accepts `alice approve 1` (T2).
- WrongStaleApprovals goes to approved after `bob approve 2`, because `{bob, carol} + 1 >= 2` (T4).
- WrongPublishInReview publishes in T6.

The important gaps are rules from INTENT.md that the TLA+ model enforces only as action guards, with no invariant
or property that states them. Because of that, neither TLC, nor `refines.py`, nor the traces would notice if they
were lost.

### A-1 (critical). "Nobody … rejects a revision they wrote", "only approvers reject", "only publishers publish" and "only the author submits" are not checked by the formalization at all

**Where.**
- `model/Approval.tla:58-62`: SeparationOfDuties and ApproverRole quantify over `approvals` only.
- `model/Approval.tla:46-52`: the guards on Reject and Publish.
- `harness/refines.py` (edge labels are `(\w+)`, which is the action name with no actor).
- `pack.yaml:257` cites `SeparationOfDuties [A1]` as the semantics of "approves **or rejects**".

**What is wrong.** The model's state does not record who rejected, who published or who submitted. So:

1. No invariant or property can express these rules, and no wrong design can be rejected by TLC for breaking them.
2. `refines.py` compares reachable states and `(action-name, successor)` edges. Another actor can always reach the
   same edge legally, so a reference model that drops the guard is "exhaustively equal" to the spec. I checked this.
   Each of the following mutants of `reference.py` gives `{"states": 1314, "transitions": 1602, "problems": []}`,
   which is identical to the baseline:
   - `reject_no_sod`: the author may reject their own revision.
   - `publish_no_role`: anyone may publish.
   - `submit_any`: anyone may submit.

   The claim in refines.py's docstring, "the service is tested against the spec, exhaustively equivalent", is
   therefore false for these rules.
3. No trace covers them. In `traces.py`, each of `reject_no_sod`, `publish_no_role`, `edit_no_role`,
   `reject_when_approved` and `approve_after_approved` is NOT CAUGHT. (`submit_any` is caught by T8's
   `bob submit 1 => NOT_AUTHOR`.)

For the shipped service, these rules are held only by hand-written asserts in `harness/lifecycle.py:48`, `:56` and `:58`.
`conformance.py` holds the service to `reference.py`, and `reference.py` is the thing that is unchecked here.

**Proposed changes.**

(a) Make the actor observable in the model. Add a history variable, for example `last \in [op: Ops, actor: Actors \cup {None}, rev: 0..MaxRev]`,
set it in every action, and add these invariants:

```tla
RejectBySeparation == last.op = "reject"  => last.actor \in Approvers /\ last.actor # author[last.rev]   \* [A1]
PublishByPublisher == last.op = "publish" => last.actor \in Publishers                                \* [A2]
EditByEditor       == last.op = "edit"    => last.actor \in Editors /\ author[rev] = last.actor        \* [A2]
SubmitByAuthor     == last.op = "submit"  => last.actor = author[rev]                                  \* (see A-3)
```

Alternatively, label edges with the actor in `refines.py`. That makes the equivalence check see actors, but it still
leaves the obligations unstated in TLA.

(b) Add wrong designs `model/wrong/WrongSelfReject.tla` and `model/wrong/WrongAnyonePublishes.tla`, each rejected by
the corresponding new invariant.

(c) Add a trace:

```yaml
- id: T9_reject_and_publish_need_the_rule           # model/wrong/WrongSelfReject.tla accepts alice's reject; WrongAnyonePublishes accepts bob's publish
  says: the author cannot reject their own revision; a non-publisher cannot publish; a non-editor cannot edit
  steps: ["alice create => OK", "carol edit => ROLE", "alice submit 1 => OK", "alice reject 1 => SEPARATION_OF_DUTIES",
          "bob approve 1 => OK", "carol approve 1 => OK", "bob publish 1 => ROLE", "carol reject 1 => WRONG_STATE", "dave publish 1 => OK"]
  end: { status: published, revision: 1, current_votes: [bob, carol] }
```

`carol reject 1 => WRONG_STATE` on an approved document also pins that an approved, not-yet-published document
cannot be rejected. INTENT.md does not say this either way (see A-4).

### A-2 (major). "Earlier approvals stay in the history" and "each revision keeps its author" are not checked by any trace end-state, and the first has no formal statement

**Where.**
- `INTENT.md` [A3] ("earlier approvals stay in the history") and [A7] ("each revision keeps its author").
- `model/Approval.tla:64-66`: there is RevisionsGrow for authors, but nothing says `approvals` only grows.
- `model/traces.yaml`: every `end:` checks only `status`, `revision` and `current_votes`.

**What is missing.**
- Formal: a design whose Edit sets `approvals' = {}` satisfies Safety, A5, A6 and A7. (`refines.py` does catch it
  against the current reference, because the states differ, but no property states the rule.)
- Traces: the `reference.py` mutants `edit_drops_history` (edit clears approvals) and `edit_rewrites_author` (edit
  re-attributes old revisions) both pass all 8 traces.

**Proposed changes.**
- Add `ApprovalsGrow == [][approvals \subseteq approvals']_vars \* [A3] history is kept` to PROPERTIES in MC.cfg.
- Add a wrong design that clears approvals on edit.
- Extend the `end:` of two traces:
  - T4 `end:` should add `approvals: [{revision: 1, actor: bob}, {revision: 1, actor: carol}, {revision: 2, actor: bob}]`.
  - T3 `end:` should add `authors: [alice, bob]`.

  `traces.py` already compares any key of `view()`.

### A-3 (major). NOT_AUTHOR, the rule "only the current revision's author submits", is in the model and SERVICE.md but not in INTENT.md

**Where.** `model/Approval.tla:36-38` (`a = author[rev]`), `harness/SERVICE.md:44`, `harness/reference.py:45`. `INTENT.md:12-20` never mentions submitting.

**What is wrong.** Here the formal statement is stronger than the intent. In T5, bob edits alice's document under
review and becomes the author of revision 2. After that alice, the document's creator, cannot submit it. INTENT.md
gives a reader no basis to expect this. It also gives no basis to expect that any editor may edit any document
(INTENT.md says "only editors … edit", which the model reads as "any editor").

**Proposed change.** Add to INTENT.md under Roles: "Any editor may edit any document that is not published; only the
author of the current revision submits it for review [A2]." Give NOT_AUTHOR a contract record or tag. Add the
`SubmitByAuthor` invariant from A-1.

### A-4 (medium). What follows "approved" and "rejected" is decided by the model but not stated or traced

**Where.** `model/Approval.tla:40-48`: Approve and Reject require `in_review`, and Submit requires `draft`.

**What is missing.** INTENT.md says only "… → approved → published, or is rejected". The model decides three further things:

1. An approved document can no longer be rejected or receive approvals. It can only be published or edited.
2. A rejected revision cannot be resubmitted. It must be edited into a new revision.
3. A rejected document can be edited by any editor.

None of these is traced. The mutants `reject_when_approved` and `approve_after_approved` pass all traces.
(`refines.py` does catch both, since the states or edges differ.)

**Proposed changes.**
- Add a sentence to INTENT.md: "Once approved, a revision can only be published or superseded by an edit; a rejected
  revision must be edited before it is reviewed again."
- Add the `carol reject 1 => WRONG_STATE` step from A-1.
- Add this trace:

```yaml
- id: T10_rejected_must_be_revised
  says: a rejected revision cannot be resubmitted; an edit starts a new revision that can be reviewed
  steps: ["alice create => OK", "alice submit 1 => OK", "bob reject 1 => OK", "alice submit 1 => WRONG_STATE",
          "alice edit => OK", "alice submit 2 => OK", "bob approve 2 => OK"]
  end: { status: in_review, revision: 2, current_votes: [bob] }
```

### A-5 (medium). Refusal precedence: half of the adjacent pairs are untested, and two orderings are arguable

**Where.** `harness/SERVICE.md:42-46`, `harness/reference.py:36-52`, `model/traces.yaml:35-39` (T8).

**What is pinned.** T8 pins ROLE > WRONG_STATE (`dave approve 1` in draft) and STALE_REVISION > WRONG_STATE
(`carol approve 9` in draft; also T5). STALE > WRONG_STATE is required by INTENT.md ("refused as STALE_REVISION"),
and after an edit the document is always in draft, so that ordering is justified.

**What is not pinned.** These reorder mutants of `reference.py` pass all traces:
- `stale_before_role`
- `sod_before_state` (SEPARATION_OF_DUTIES checked before WRONG_STATE)
- `notauthor_before_state`

T8's `says:` claims "a missing role is reported before anything else". But its only ROLE refusal on a document,
`dave approve 1`, names the current revision, so ROLE vs STALE is never exercised.

**Arguable orderings.**
- WRONG_STATE before SEPARATION_OF_DUTIES. The same command, "alice approves her own revision 1", gets WRONG_STATE
  while the document is in draft and SEPARATION_OF_DUTIES once it is in review. Separation of duties is a
  permanent fact about (actor, revision), like ROLE is about the actor. The principle that puts ROLE first
  ("permanent facts before transient state") would put SEPARATION_OF_DUTIES before WRONG_STATE too.
- The same applies to NOT_AUTHOR vs WRONG_STATE (`bob submit 1` on a document in review gives WRONG_STATE).

The current order is defensible as a layering: caller, then target, then state, then relationship, then history.
But SERVICE.md gives no rationale.

**Proposed changes.**
- Add one sentence of rationale to SERVICE.md § Refusals. If the authors prefer "permanent before transient",
  reorder to ROLE, STALE_REVISION, SEPARATION_OF_DUTIES, NOT_AUTHOR, WRONG_STATE, ALREADY_APPROVED.
- Whichever order is chosen, pin each adjacent pair:

```yaml
- id: T11_precedence_pairs
  says: each adjacent pair of the refusal order, with both rules applying
  steps: ["alice create => OK", "dave approve 9 => ROLE",               # ROLE before STALE_REVISION
          "alice approve 1 => WRONG_STATE",                              # WRONG_STATE before SEPARATION_OF_DUTIES (as now)
          "alice submit 1 => OK", "bob submit 1 => WRONG_STATE",         # WRONG_STATE before NOT_AUTHOR (as now)
          "bob approve 1 => OK", "carol approve 1 => OK", "bob approve 1 => WRONG_STATE"]   # WRONG_STATE before ALREADY_APPROVED
  end: { status: approved, revision: 1, current_votes: [bob, carol] }
```

### A-6 (minor). STALE_REVISION is also returned for a revision that does not exist yet

**Where.** `harness/reference.py:42` (`revision != d.rev`); T8's `carol approve 9 => STALE_REVISION` (`traces.yaml:37`).

**What is wrong.** INTENT.md describes STALE_REVISION as "a command naming a **superseded** revision". Revision 9 of
a one-revision document was never superseded. SERVICE.md's "not current" is the actual rule. The name is mildly
misleading for a client: "refresh and retry" does not help with a future revision.

**Proposed change.** Either align INTENT.md with SERVICE.md ("names a revision that is not the current one"), or
split out an `UNKNOWN_REVISION` reason. The first is cheaper, and T8 already pins the behaviour.

### A-7 (minor). The wrong designs exercise only invariants; A5, A6 and A7 have no wrong design, and WrongPublishInReview is checked against the wrong property

**Where.** `model/wrong/MCWrongPublishInReview.cfg:9` checks only `BoundToRevision`; no wrong cfg lists any PROPERTIES.

**What is wrong.** WrongPublishInReview's defect is exactly [A6] PublishOnlyApproved. It is caught today only
because publishing with fewer than two votes also breaks [A3]. If [A3] were weakened, nothing would show that [A6]
still rejects anything. [A5] PublishedIsFinal and [A7] RevisionsGrow are never shown to reject any design.

**Proposed changes.**
- Add `PROPERTIES PublishOnlyApproved` to MCWrongPublishInReview.cfg, and assert that the violation names it.
- Add a wrong design that allows Edit after publish (T7's `bob edit` already separates it), checked against
  `PublishedIsFinal`.
- Add a wrong design that rewrites `author` on edit, checked against `RevisionsGrow`.

### A-8 (minor). INTENT.md does not mention the ALREADY_APPROVED refusal

**Where.** `harness/SERVICE.md:45`, T8 `bob approve 1 => ALREADY_APPROVED`.

**What is missing.** "Two distinct approvers" justifies that a repeat vote does not count. It does not say whether a
repeat is refused or accepted as a no-op. The pack refuses it, and that is fine, but INTENT.md should say so in one clause.

### Checked and fine

- A3 `BoundToRevision` with SeparationOfDuties and ApproverRole: approved or published ⇒ at least two distinct
  approvers recorded on the current revision, none of them its author. This matches INTENT.md. `Votes` is a set, so
  the approvers are distinct by construction.
- The quorum is exactly 2: the `quorum_three` mutant is caught by T1, T3 and T7.
- Edit from approved or in review returns the document to draft (T4, T5), as INTENT.md says ("any edit … sends it back to draft").
- Editing a published document is refused (T7).
- Separation of duties is per revision (T3), as INTENT.md says.
- The safety obligations do not state that a second distinct approval moves the document to approved; that is
  carried by the action and pinned by T1 and T3. This is acceptable, but note that a design that never approves
  satisfies every invariant. Only the traces and `refines.py` rule it out.

---

## Reproduction (scratchpad)

- Booking spec mutants: `review/spec_a` (closed at the requester's end), `review/spec_b` (one-minute overlaps
  ignored), `review/spec_c` (minimum two minutes). Each copies `packs/booking/spec` with `BookingSpec.dfy:17-18`
  edited. Ran `dafny test --target py traces.dfy`: 8 verified, 8 PASSED in all three.
- Approval trace mutants: `review/approval_mut/<name>/harness/reference.py`, run with `python3 -I .../harness/traces.py`.
  - NOT CAUGHT: reject_no_sod, publish_no_role, edit_no_role, edit_drops_history, edit_rewrites_author,
    reject_when_approved, approve_after_approved, sod_before_state, notauthor_before_state, stale_before_role.
  - CAUGHT: quorum_three, future_rev_wrong_state.
- Approval refinement mutants: `review/refmut/<name>` (a copy of model/ and harness/ with a mutated reference.py),
  run with `TLA2TOOLS=... python3 -I harness/refines.py`.
  - reject_no_sod, publish_no_role and submit_any: identical to the baseline (1314 states, 1602 transitions, no problems).
  - edit_drops_history: caught.

---

## Response (applied in v0.8.0 before sealing)

The review was made by an agent that did not write either pack, working from INTENT.md first; it is an
independent review, not a human one. Every finding was taken; none was declined.

| Finding | Change |
|---|---|
| B-1 | `spec/traces.dfy` T9 (touching from below); wrong core `spec/wrong/closed_at_end.dfy` |
| B-2 | T10 (one-minute overlap on both sides); wrong core `spec/wrong/ignores_one_minute_overlap.dfy`; `harness/conformance.py` nudges every endpoint by up to one minute; `harness/lifecycle.py` books one-minute overlaps |
| B-3 | T4 books `[600, 601)`; `harness/lifecycle.py` books a one-minute interval |
| B-4 | T11 (move to an empty interval, unknown id, NotActive before Invalid) |
| B-5 | T5 has a second booking the cancel must leave alone, and cancels an unknown id |
| B-6 | T6 also shifts a booking over its own time, ending where a neighbour starts |
| B-7 | INTENT.md: "whole minutes on an abstract, timezone-free line, not bounded to one day" |
| A-1 | `model/Approval.tla` history variable `last` and invariants RejectBySeparation, PublishByPublisher, EditByEditor, SubmitByAuthor; `harness/reference.py` and `harness/refines.py` carry and compare `last`, so a reference with the wrong actor fails refinement (checked: reject_no_sod, publish_no_role, submit_any each now differ in 438 states); wrong designs WrongSelfReject, WrongAnyonePublishes; trace T9 |
| A-2 | ApprovalsGrow property; wrong designs WrongEditClearsHistory, WrongEditRewritesAuthors; T3 and T4 end states check `authors` and `approvals` |
| A-3 | INTENT.md: any editor edits and becomes the revision's author; only the current revision's author submits; contract record A8 |
| A-4 | INTENT.md: what follows approval and rejection; T9 (`carol reject 1 => WRONG_STATE` on an approved document), T10 |
| A-5 | Order kept, rationale added to `harness/SERVICE.md` § Refusals; T11 pins every adjacent pair (checked: sod_before_state and stale_before_role now fail T11) |
| A-6 | INTENT.md: STALE_REVISION is any revision other than the current one |
| A-7 | WrongPublishInReview checked against PublishOnlyApproved; WrongEditAfterPublish against PublishedIsFinal; WrongEditRewritesAuthors against RevisionsGrow. This needed one evaluator change: the `tlc` kind's `{violated: X}` now also accepts an action property (RFC 0002 § 4) |
| A-8 | INTENT.md names ALREADY_APPROVED |

All twelve of the reviewer's approval reference mutants and the three booking spec mutants are now caught by a
trace, by refinement, or both.
