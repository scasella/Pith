// Known-wrong core: a fixed-window counter. It counts what key k was granted since the start of the current
// fixed bucket [floor(now / window) * window, now] and grants when that fits. Right after a bucket boundary the
// count starts again from zero, so up to twice the limit can be granted within one window of the configured
// length. Violates [Q0] (window safety) and [Q1] (granted exactly when it fits in the sliding window).
// REJECTED-BY: [Q0] [Q1]
// DIFFERS-ON: T2_NoBurstAcrossABucketBoundary
include "../QuotaSpec.dfy"
module Wrong {
  import opened QuotaSpec
  function Since(log: seq<Entry>, k: string, b: nat): nat {
    if |log| == 0 then 0 else Since(log[..|log| - 1], k, b) + (if log[|log| - 1].key == k && log[|log| - 1].t >= b then log[|log| - 1].cost else 0)
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
      var u := Since(s.log, k, (now / c.window) * c.window);
      if u + cost <= c.limit {
        d, s' := Granted(c.limit - u - cost), State(now, s.log + [Entry(k, now, cost)]);
      } else {
        d, s' := Denied(if u <= c.limit then c.limit - u else 0, if cost > c.limit then None else Some(c.window - now % c.window)), State(now, s.log);
      }
    }
  }
}
