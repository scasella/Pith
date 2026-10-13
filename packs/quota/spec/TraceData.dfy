// TraceData.dfy — the reviewed accepting and rejecting traces, as data. FROZEN.
// Each trace is a configuration (default limit, window, the keys with a limit of their own) and a sequence of calls
// with the decision the contract requires at each step,
// worked out by hand from INTENT.md (the arithmetic is in the comments). They run against the verified core on every
// judge (spec/traces.dfy, check core.traces), and against every known-wrong core (harness/adequacy.py, check
// core.adequacy), each of which must give a different decision on the trace its header names (DIFFERS-ON).
// `python3 harness/adequacy.py --print` prints them for review.
include "QuotaSpec.dfy"

module QuotaTraces {
  import opened QuotaSpec

  datatype Step = Step(key: string, cost: nat, now: nat, want: Decision)
  datatype Trace = Trace(name: string, c: Config, steps: seq<Step>)

  function G(rem: nat): Decision { Granted(rem) }
  function D(rem: nat, retry: nat): Decision { Denied(rem, Some(retry)) }
  function Never(rem: nat): Decision { Denied(rem, None) }

  function All(): seq<Trace>
  {
    [
      // T1 the window is half-open: a grant at 0 with window 10 counts at 9 and no longer at 10.
      Trace("T1_GrantExpiresExactlyOneWindowLater", Config(2, 10, map[]), [
        Step("a", 2, 0, G(0)),            // 0 + 2 <= 2
        Step("a", 1, 9, D(0, 1)),         // the grant at 0 still counts at 9; it stops counting at 10 = 9 + 1
        Step("a", 1, 10, G(1))            // nothing counts at 10: 0 + 1 <= 2, 1 left
      ]),
      // T2 every window of length 10, not only the fixed buckets [0,10), [10,20), ...: 3 granted at 8 still count at 11.
      Trace("T2_NoBurstAcrossABucketBoundary", Config(3, 10, map[]), [
        Step("a", 3, 8, G(0)),
        Step("a", 1, 11, D(0, 7)),        // the grant at 8 counts until 18 = 11 + 7
        Step("a", 1, 17, D(0, 1)),
        Step("a", 3, 18, G(0))
      ]),
      // T3 a denial consumes nothing: asking again while over quota does not push the recovery back.
      Trace("T3_DenialsConsumeNothing", Config(2, 10, map[]), [
        Step("a", 2, 0, G(0)),
        Step("a", 1, 5, D(0, 5)),
        Step("a", 1, 6, D(0, 4)),
        Step("a", 2, 10, G(0))            // only the grant at 0 ever counted, and it expired at 10
      ]),
      // T4 the retry hint waits for ENOUGH to expire, not for the first expiry.
      Trace("T4_RetryWaitsUntilEnoughHasExpired", Config(3, 10, map[]), [
        Step("a", 1, 0, G(2)),
        Step("a", 1, 2, G(1)),
        Step("a", 1, 4, G(0)),
        Step("a", 2, 5, D(0, 7)),         // needs used <= 1: the grants at 0 and 2 must expire; 2 expires at 12 = 5 + 7
        Step("a", 2, 11, D(1, 1)),        // at 11 the grants at 2 and 4 count (2 used, 1 left)
        Step("a", 2, 12, G(0))            // at 12 only the grant at 4 counts: 1 + 2 <= 3
      ]),
      // T5 a cost above the limit is denied with no retry hint; it consumes nothing.
      Trace("T5_CostAboveTheLimitNeverFits", Config(3, 10, map[]), [
        Step("a", 4, 0, Never(3)),
        Step("a", 3, 0, G(0))
      ]),
      // T6 keys are independent quotas.
      Trace("T6_KeysAreIndependent", Config(1, 10, map[]), [
        Step("a", 1, 0, G(0)),
        Step("b", 1, 0, G(0)),
        Step("a", 1, 1, D(0, 9)),
        Step("b", 1, 10, G(0))
      ]),
      // T7 the clock never runs backwards; a regressed call changes nothing; the same instant again is fine.
      Trace("T7_TheClockNeverRunsBackwards", Config(2, 10, map[]), [
        Step("a", 1, 5, G(1)),
        Step("a", 1, 4, Regressed),
        Step("b", 1, 4, Regressed),       // the clock is shared by every key
        Step("a", 1, 5, G(0))
      ]),
      // T8 sliding, step by step, with a short window.
      Trace("T8_TheWindowSlides", Config(2, 5, map[]), [
        Step("a", 1, 0, G(1)),
        Step("a", 1, 1, G(0)),
        Step("a", 1, 5, G(0)),            // the grant at 0 expired at 5; the one at 1 counts until 6
        Step("a", 2, 6, D(1, 4)),         // at 6 only the grant at 5 counts; it expires at 10 = 6 + 4
        Step("a", 1, 6, G(0))
      ]),
      // T9 each key is held to its own limit: "vip" has 4, every other key the default 2.
      Trace("T9_EachKeyIsHeldToItsOwnLimit", Config(2, 10, map["vip" := 4]), [
        Step("vip", 1, 0, G(3)),
        Step("vip", 1, 1, G(2)),
        Step("vip", 1, 2, G(1)),          // past the default: vip's own limit is 4
        Step("vip", 1, 3, G(0)),
        Step("vip", 1, 4, D(0, 6)),       // needs vip's used <= 3: the grant at 0 expires at 10 = 4 + 6 (against the default 2 it would be 12)
        Step("a", 1, 4, G(1)),            // a key without a limit of its own has the default
        Step("a", 1, 4, G(0)),
        Step("a", 1, 5, D(0, 9)),         // held to the default: both grants at 4 count until 14 = 5 + 9
        Step("vip", 3, 5, D(0, 7)),       // 3 <= 4 can fit: needs used <= 1, only the grant at 3 counts at 12 = 5 + 7
        Step("vip", 5, 5, Never(0)),      // 5 > 4: never
        Step("vip", 3, 12, G(0)),         // at 12 the grant at 3 counts: 1 + 3 <= 4
        Step("a", 2, 14, G(0))            // the grants at 4 stopped counting at 14
      ]),
      // T10 a key's own limit can be below the default: "free" has 1, every other key the default 3.
      Trace("T10_AKeyCanHaveALowerLimit", Config(3, 10, map["free" := 1]), [
        Step("free", 1, 0, G(0)),
        Step("free", 1, 1, D(0, 9)),      // free's limit is 1: the grant at 0 counts until 10 = 1 + 9
        Step("other", 1, 1, G(2)),
        Step("free", 2, 2, Never(0)),     // 2 > 1: never, although 2 is within the default
        Step("free", 1, 10, G(0))
      ])
    ]
  }

  // The index of the first step whose decision differs from the trace, or -1. -2 marks a malformed trace.
  method Run(a: Acquirer, t: Trace) returns (mismatch: int)
  {
    if !ValidConfig(t.c) { return -2; }
    var s := Initial();
    var i := 0;
    while i < |t.steps|
      invariant Valid(t.c, s)
    {
      var st := t.steps[i];
      if st.cost < 1 { return -2; }
      var d, s' := a.Acquire(t.c, s, st.key, st.cost, st.now);
      if d != st.want { return i; }
      s := s';
      i := i + 1;
    }
    return -1;
  }
}
