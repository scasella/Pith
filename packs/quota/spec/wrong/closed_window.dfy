// Known-wrong core: an off-by-one window. It counts a grant made at e.t while e.t >= now - window, i.e. over the
// closed window [now - window, now], so a grant still counts at the instant it should have expired (e.t + window).
// Safe (never grants more than the limit; Dafny cannot show that without a lemma, which is beside the point) but
// violates [Q1]: at exactly e.t + window the contract grants.
// REJECTED-BY: [Q1]
// DIFFERS-ON: T1_GrantExpiresExactlyOneWindowLater
include "../QuotaSpec.dfy"
module Wrong {
  import opened QuotaSpec
  function UsedClosed(log: seq<Entry>, k: string, t: nat, w: nat): nat {
    if |log| == 0 then 0 else UsedClosed(log[..|log| - 1], k, t, w) + (if log[|log| - 1].key == k && log[|log| - 1].t <= t && t <= log[|log| - 1].t + w then log[|log| - 1].cost else 0)
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
      ensures d.Granted? ==> d.remaining == c.limit - Used(s.log, k, now, c.window) - cost    // [Q3]
      ensures d.Denied? ==> d.remaining == c.limit - Used(s.log, k, now, c.window)            // [Q3]
      ensures d.Denied? ==> (d.retryAfter.None? <==> cost > c.limit)                         // [Q4]
      ensures d.Denied? && d.retryAfter.Some? ==>                                             // [Q4]
                d.retryAfter.value >= 1 && FitsAfter(c, s.log, k, cost, now, d.retryAfter.value) &&     // [Q4]
                forall r :: 1 <= r < d.retryAfter.value ==> !FitsAfter(c, s.log, k, cost, now, r)       // [Q4]
    {
      if now < s.clock { return Regressed, s; }
      var u := UsedClosed(s.log, k, now, c.window);
      if u + cost <= c.limit {
        d, s' := Granted(c.limit - u - cost), State(now, s.log + [Entry(k, now, cost)]);
      } else {
        d, s' := Denied(if u <= c.limit then c.limit - u else 0, if cost > c.limit then None else Some(1)), State(now, s.log);
      }
    }
  }
}
