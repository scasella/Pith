// QuotaCore.dfy — the pack's verified core. It includes spec/QuotaSpec.dfy and may not modify it.
// Translated to Python (harness/oracle-py/) by harness/translate.py; the black-box harnesses judge the candidate's
// library against that translation. The core favours obviously-correct over fast: it is an oracle, not a product.
include "QuotaSpec.dfy"

module QuotaCore {
  import opened QuotaSpec

  // ---- lemmas ------------------------------------------------------------------------------------------------------

  lemma UsedAppend(log: seq<Entry>, e: Entry, k: string, t: nat, w: nat)
    ensures Used(log + [e], k, t, w) == Used(log, k, t, w) + (if Counts(e, k, t, w) then e.cost else 0)
  {
    assert (log + [e])[..|log + [e]| - 1] == log;
  }

  // Every grant is at or before `now`, and now <= t: whatever counts at t also counts at now.
  lemma UsedLater(log: seq<Entry>, k: string, now: nat, t: nat, w: nat)
    requires forall i :: 0 <= i < |log| ==> log[i].t <= now
    requires now <= t
    ensures Used(log, k, t, w) <= Used(log, k, now, w)
  {
    if |log| > 0 {
      var p := log[..|log| - 1];
      assert forall i :: 0 <= i < |p| ==> p[i].t <= now by { forall i | 0 <= i < |p| ensures p[i].t <= now { assert p[i] == log[i]; } }
      UsedLater(p, k, now, t, w);
    }
  }

  // A full window after the clock, nothing counts any more.
  lemma UsedExpires(log: seq<Entry>, k: string, now: nat, w: nat)
    requires forall i :: 0 <= i < |log| ==> log[i].t <= now
    ensures Used(log, k, now + w, w) == 0
  {
    if |log| > 0 {
      var p := log[..|log| - 1];
      assert forall i :: 0 <= i < |p| ==> p[i].t <= now by { forall i | 0 <= i < |p| ensures p[i].t <= now { assert p[i] == log[i]; } }
      UsedExpires(p, k, now, w);
    }
  }

  // Appending a grant that fits at `now`, at `now` >= every earlier grant, keeps every window of every key within
  // that key's limit.
  lemma GrantKeepsWindowsSafe(c: Config, log: seq<Entry>, k: string, cost: nat, now: nat)
    requires WindowSafe(c, log)
    requires forall i :: 0 <= i < |log| ==> log[i].t <= now
    requires FitsAt(c, log, k, cost, now)
    ensures WindowSafe(c, log + [Entry(k, now, cost)])
  {
    var e := Entry(k, now, cost);
    forall k2: string, t: nat ensures Used(log + [e], k2, t, c.window) <= LimitOf(c, k2) {
      UsedAppend(log, e, k2, t, c.window);
      if Counts(e, k2, t, c.window) {
        assert k2 == k && now <= t;
        UsedLater(log, k, now, t, c.window);
      }
    }
  }

  // ---- computations ------------------------------------------------------------------------------------------------

  method ComputeUsed(log: seq<Entry>, k: string, t: nat, w: nat) returns (u: nat)
    ensures u == Used(log, k, t, w)
  {
    u := 0;
    var i := 0;
    while i < |log|
      invariant 0 <= i <= |log|
      invariant u == Used(log[..i], k, t, w)
    {
      assert log[..i + 1] == log[..i] + [log[i]];
      UsedAppend(log[..i], log[i], k, t, w);
      if Counts(log[i], k, t, w) { u := u + log[i].cost; }
      i := i + 1;
    }
    assert log[..|log|] == log;
  }

  // The least r >= 1 at which the request fits, given that nothing else is granted meanwhile.
  method EarliestFit(c: Config, log: seq<Entry>, k: string, cost: nat, now: nat) returns (r: nat)
    requires ValidConfig(c) && cost <= LimitOf(c, k)
    requires forall i :: 0 <= i < |log| ==> log[i].t <= now
    ensures r >= 1 && FitsAfter(c, log, k, cost, now, r)
    ensures forall q :: 1 <= q < r ==> !FitsAfter(c, log, k, cost, now, q)
  {
    UsedExpires(log, k, now, c.window);
    r := 1;
    var u := ComputeUsed(log, k, now + r, c.window);
    while u + cost > LimitOf(c, k)
      invariant 1 <= r <= c.window
      invariant u == Used(log, k, now + r, c.window)
      invariant forall q :: 1 <= q < r ==> !FitsAfter(c, log, k, cost, now, q)
      decreases c.window - r
    {
      if r == c.window { assert false; }          // Used is 0 a full window after `now` (UsedExpires)
      r := r + 1;
      u := ComputeUsed(log, k, now + r, c.window);
    }
  }

  class Core extends Acquirer, Peeker, LimitReporter {

    constructor () {}

    method Acquire(c: Config, s: State, k: string, cost: nat, now: nat) returns (d: Decision, s': State)
      requires ValidConfig(c) && Valid(c, s) && cost >= 1
      ensures Valid(c, s')
      ensures d.Regressed? <==> now < s.clock
      ensures d.Regressed? ==> s' == s
      ensures !d.Regressed? ==> s'.clock == now
      ensures d.Granted? <==> now >= s.clock && FitsAt(c, s.log, k, cost, now)
      ensures d.Granted? ==> s'.log == s.log + [Entry(k, now, cost)]
      ensures d.Denied? ==> s'.log == s.log
      ensures d.Granted? ==> d.remaining == LimitOf(c, k) - Used(s.log, k, now, c.window) - cost
      ensures d.Denied? ==> d.remaining == LimitOf(c, k) - Used(s.log, k, now, c.window)
      ensures d.Denied? ==> (d.retryAfter.None? <==> cost > LimitOf(c, k))
      ensures d.Denied? && d.retryAfter.Some? ==>
                d.retryAfter.value >= 1 && FitsAfter(c, s.log, k, cost, now, d.retryAfter.value) &&
                forall r :: 1 <= r < d.retryAfter.value ==> !FitsAfter(c, s.log, k, cost, now, r)
    {
      if now < s.clock { return Regressed, s; }
      var lim := LimitOf(c, k);
      var u := ComputeUsed(s.log, k, now, c.window);
      assert u <= lim;                                           // WindowSafe at (k, now)
      if u + cost <= lim {
        GrantKeepsWindowsSafe(c, s.log, k, cost, now);
        d := Granted(lim - u - cost);
        s' := State(now, s.log + [Entry(k, now, cost)]);
      } else if cost > lim {
        d := Denied(lim - u, None);
        s' := State(now, s.log);
      } else {
        var r := EarliestFit(c, s.log, k, cost, now);
        d := Denied(lim - u, Some(r));
        s' := State(now, s.log);
      }
    }

    method Peek(c: Config, s: State, k: string, now: nat) returns (regressed: bool, remaining: nat, s': State)
      requires ValidConfig(c) && Valid(c, s)
      ensures Valid(c, s')
      ensures regressed <==> now < s.clock
      ensures regressed ==> s' == s
      ensures !regressed ==> s' == State(now, s.log)
      ensures !regressed ==> remaining == LimitOf(c, k) - Used(s.log, k, now, c.window)
    {
      if now < s.clock { return true, 0, s; }
      var u := ComputeUsed(s.log, k, now, c.window);
      assert u <= LimitOf(c, k);
      return false, LimitOf(c, k) - u, State(now, s.log);
    }

    method LimitFor(c: Config, k: string) returns (l: nat)
      requires ValidConfig(c)
      ensures l == LimitOf(c, k)
    {
      l := LimitOf(c, k);
    }
  }
}
