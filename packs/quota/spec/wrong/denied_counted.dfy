// Known-wrong core: denied requests are logged as if granted, so a client that keeps asking while over its quota
// keeps itself locked out. Each decision is computed by the verified core, but the state it leaves violates [Q2]
// (a denial consumes nothing) and, through the log, [Q0].
// REJECTED-BY: [Q2] [Q0]
// DIFFERS-ON: T3_DenialsConsumeNothing
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
      if d.Denied? { s' := State(now, s.log + [Entry(k, now, cost)]); }
    }
  }
}
