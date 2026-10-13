// Known-wrong core: per-key limits applied to granting and to `remaining`, but the retry hint still worked out
// against the limiter's default limit, as version 1 did (the search, and the "can never fit" test, were not updated).
// For a key with a limit of its own above the default, the hint is later than the earliest instant the request fits,
// or missing although the request would fit; below the default, it is too early. Violates [Q4]. Everything else is
// the verified core.
// REJECTED-BY: [Q4]
// DIFFERS-ON: T9_EachKeyIsHeldToItsOwnLimit
include "../QuotaCore.dfy"
module Wrong {
  import opened QuotaSpec
  import QuotaCore
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
      if d.Denied? {
        var v1 := Config(c.limit, c.window, map[]);                  // the default limit, as if no key had its own
        if cost > c.limit { d := Denied(d.remaining, None); }
        else {
          var r := QuotaCore.EarliestFit(v1, s.log, k, cost, now);
          d := Denied(d.remaining, Some(r));
        }
      }
    }
  }
}
