// traces.dfy — concrete satisfying traces, executed against the submitted implementation.
// These are trace-review artifacts. Provenance (who approved them as intended, when) is recorded in
// traces.provenance.yaml; in this seed release that file is UNSIGNED and the traces are illustrative.
// `dafny test` runs them; `expect` failures are runtime failures, not proof failures.
include "../core/AuthCore.dfy"

module Traces {
  import opened AuthSpec
  import opened AuthCore

  const Fresh := Account(100, 0, map[], map[])

  method {:test} T1_EqualityAuthorizes() {
    var c := new Core();
    var d, a1 := c.Decide(Fresh, Request(1, 100));      // exactly the available limit
    expect d == Authorized;
    expect a1.holds == map[1 := 100];
    expect a1.status == map[1 := Auth];
  }

  method {:test} T2_OverLimitDeclinesWithoutHold() {
    var c := new Core();
    var d, a1 := c.Decide(Fresh, Request(1, 101));
    expect d == Declined;
    expect a1.holds == map[];
    expect a1.status == map[1 := Decl];
  }

  method {:test} T3_TwoOfSixtyAgainstHundred() {
    // The snapshot counterexample, run through the atomic model: the second request
    // sees the first hold and is declined. (A receipt-time policy would authorize both.)
    var c := new Core();
    var d1, a1 := c.Decide(Fresh, Request(1, 60));
    var d2, a2 := c.Decide(a1, Request(2, 60));
    expect d1 == Authorized && d2 == Declined;
    expect a2.holds == map[1 := 60];
  }

  method {:test} T4_ReleaseFreesFunds() {
    var c := new Core();
    var d1, a1 := c.Decide(Fresh, Request(1, 60));
    var a2 := c.Release(a1, 1);
    expect a2.holds == map[] && a2.status == map[1 := Rel];
    var d3, a3 := c.Decide(a2, Request(2, 100));
    expect d3 == Authorized;
  }

  method {:test} T5_DeclinedIsTerminal() {
    var c := new Core();
    var d1, a1 := c.Decide(Fresh, Request(1, 101));
    var d2, a2 := c.Decide(a1, Request(2, 10));
    expect a2.status[1] == Decl;                          // untouched by the later decision
    expect d2 == Authorized;
  }
}
