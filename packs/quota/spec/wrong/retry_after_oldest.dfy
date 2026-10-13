// Known-wrong core: on a denial, the retry hint is the instant the OLDEST counting grant expires. When more than
// one grant must expire before the request fits, a client that waits exactly that long is denied again.
// Violates [Q4] (the hint is the earliest instant at which the request fits). Everything else is the verified core.
// REJECTED-BY: [Q4]
// DIFFERS-ON: T4_RetryWaitsUntilEnoughHasExpired
include "../QuotaCore.dfy"
module Wrong {
  import opened QuotaSpec
  import QuotaCore
  function Oldest(log: seq<Entry>, k: string, t: nat, w: nat): Option<nat> {
    if |log| == 0 then None
    else if Counts(log[0], k, t, w) then Some(log[0].t) else Oldest(log[1..], k, t, w)
  }
  class C extends Acquirer {
    constructor () {}
    method Acquire(c: Config, s: State, k: string, cost: nat, now: nat) returns (d: Decision, s': State)
      requires ValidConfig(c) && Valid(c, s) && cost >= 1
      ensures Valid(c, s')                                                                    // [Q0]
      ensures d.Regressed? <==> now < s.clock                                                 // [CLOCK]
      ensures d.Regressed? ==> s' == s                                                        // [CLOCK]
      ensures !d.Regressed? ==> s'.clock == now                                               // [CLOCK]
      ensures d.Granted? <==> now >= s.clock && FitsAt(c, s.log, k, cost, now)               // [Q1]
      ensures d.Granted? ==> s'.log == s.log + [Entry(k, now, cost)]                          // [Q2]
      ensures d.Denied? ==> s'.log == s.log                                                   // [Q2]
      ensures d.Granted? ==> d.remaining == LimitOf(c, k) - Used(s.log, k, now, c.window) - cost  // [Q3]
      ensures d.Denied? ==> d.remaining == LimitOf(c, k) - Used(s.log, k, now, c.window)         // [Q3]
      ensures d.Denied? ==> (d.retryAfter.None? <==> cost > LimitOf(c, k))                    // [Q4]
      ensures d.Denied? && d.retryAfter.Some? ==>                                             // [Q4]
                d.retryAfter.value >= 1 && FitsAfter(c, s.log, k, cost, now, d.retryAfter.value) &&     // [Q4]
                forall r :: 1 <= r < d.retryAfter.value ==> !FitsAfter(c, s.log, k, cost, now, r)       // [Q4]
    {
      var core := new QuotaCore.Core();
      d, s' := core.Acquire(c, s, k, cost, now);
      if d.Denied? && d.retryAfter.Some? {
        var o := Oldest(s.log, k, now, c.window);
        if o.Some? && o.value + c.window > now { d := Denied(d.remaining, Some(o.value + c.window - now)); }
      }
    }
  }
}
