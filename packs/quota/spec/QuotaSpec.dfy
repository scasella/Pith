// QuotaSpec.dfy — the sliding-window quota contract. This file is the oracle; cores may not edit it.
// Obligation tags in square brackets are named by the pack's contract records (pack.yaml:contracts).
//
// One limiter has a configuration (a limit and a window length, both whole positive numbers), a clock (the latest
// instant any call has named) and a log of grants. Time is an INPUT: every call names its instant `now`, a whole
// number on an abstract line (the library never reads a wall clock). Keys are independent quotas sharing one clock.
module QuotaSpec {

  datatype Config = Config(limit: nat, window: nat)
  predicate ValidConfig(c: Config) { c.limit >= 1 && c.window >= 1 }

  datatype Entry = Entry(key: string, t: nat, cost: nat)                 // one grant: who, when, how much
  datatype State = State(clock: nat, log: seq<Entry>)
  datatype Option<T> = None | Some(value: T)
  datatype Decision = Granted(remaining: nat) | Denied(remaining: nat, retryAfter: Option<nat>) | Regressed

  function Initial(): State { State(0, []) }

  // ---- the window convention -----------------------------------------------------------------------------------

  // [WINDOW] a grant made at instant e.t counts at instant t exactly when t - window < e.t <= t: the window ending at
  // t is half-open, (t - window, t]. A grant stops counting at exactly e.t + window.
  predicate Counts(e: Entry, k: string, t: nat, w: nat) { e.key == k && e.t <= t && t < e.t + w }

  // What key k has been granted in the window ending at instant t.
  function Used(log: seq<Entry>, k: string, t: nat, w: nat): nat
  {
    if |log| == 0 then 0
    else Used(log[..|log| - 1], k, t, w) + (if Counts(log[|log| - 1], k, t, w) then log[|log| - 1].cost else 0)
  }

  predicate FitsAt(c: Config, log: seq<Entry>, k: string, cost: nat, t: nat) { Used(log, k, t, c.window) + cost <= c.limit }
  // [Q4] the same request would fit r instants after `now`, if nothing else were granted meanwhile
  predicate FitsAfter(c: Config, log: seq<Entry>, k: string, cost: nat, now: nat, r: nat) { FitsAt(c, log, k, cost, now + r) }

  // ---- state invariant ---------------------------------------------------------------------------------------------

  // [Q0] in EVERY window of the configured length, at every instant (not only at instants where a call was made),
  // what each key was granted is within the limit.
  ghost predicate WindowSafe(c: Config, log: seq<Entry>) { forall k: string, t: nat :: Used(log, k, t, c.window) <= c.limit }

  ghost predicate Valid(c: Config, s: State)
  {
    && (forall i :: 0 <= i < |s.log| ==> s.log[i].cost >= 1 && s.log[i].t <= s.clock)    // grants are in the past
    && WindowSafe(c, s.log)                                                                 // [Q0]
  }

  // ---- obligations -------------------------------------------------------------------------------------------------

  trait {:termination false} Acquirer {
    // Ask for `cost` units of key k's quota at instant `now`.
    method Acquire(c: Config, s: State, k: string, cost: nat, now: nat) returns (d: Decision, s': State)
      requires ValidConfig(c) && Valid(c, s) && cost >= 1
      ensures Valid(c, s')                                                                    // [Q0] preserved
      ensures d.Regressed? <==> now < s.clock                                                 // [CLOCK] the clock never runs backwards
      ensures d.Regressed? ==> s' == s                                                        // [CLOCK] a regressed call changes nothing
      ensures !d.Regressed? ==> s'.clock == now                                               // [CLOCK] every other call advances the clock
      ensures d.Granted? <==> now >= s.clock && FitsAt(c, s.log, k, cost, now)               // [Q1] granted exactly when it fits
      ensures d.Granted? ==> s'.log == s.log + [Entry(k, now, cost)]                          // [Q2] a grant records exactly itself
      ensures d.Denied? ==> s'.log == s.log                                                   // [Q2] a denial consumes nothing
      ensures d.Granted? ==> d.remaining == c.limit - Used(s.log, k, now, c.window) - cost    // [Q3] what is left after the grant
      ensures d.Denied? ==> d.remaining == c.limit - Used(s.log, k, now, c.window)            // [Q3] what is left now
      ensures d.Denied? ==> (d.retryAfter.None? <==> cost > c.limit)                         // [Q4] never grantable: no retry hint
      ensures d.Denied? && d.retryAfter.Some? ==>                                             // [Q4] the earliest instant it would fit
                d.retryAfter.value >= 1 && FitsAfter(c, s.log, k, cost, now, d.retryAfter.value) &&
                forall r :: 1 <= r < d.retryAfter.value ==> !FitsAfter(c, s.log, k, cost, now, r)
  }

  trait {:termination false} Peeker {
    // What key k could still be granted at instant `now`, without asking for it.
    method Peek(c: Config, s: State, k: string, now: nat) returns (regressed: bool, remaining: nat, s': State)
      requires ValidConfig(c) && Valid(c, s)
      ensures Valid(c, s')
      ensures regressed <==> now < s.clock                                                    // [CLOCK]
      ensures regressed ==> s' == s                                                           // [CLOCK]
      ensures !regressed ==> s' == State(now, s.log)                                          // [Q5] a peek grants nothing, advances the clock
      ensures !regressed ==> remaining == c.limit - Used(s.log, k, now, c.window)            // [Q5]
  }
}
