// AuthSpec.dfy — the template. This file is the oracle. Implementations may not edit it.
// Obligation tags in square brackets are read by gate/gate.py.
module AuthSpec {

  type ReqId = nat

  datatype Decision = Authorized | Declined
  datatype Status   = Auth | Decl | Rel | Post      // Post: captured (see PostingSpec.dfy)
  datatype Request  = Request(id: ReqId, amount: nat)

  // State of one account. `holds` are live reservations keyed by request.
  datatype Account = Account(limit: nat, posted: nat, holds: map<ReqId, nat>, status: map<ReqId, Status>)

  // ---- derived quantities -------------------------------------------------

  ghost function Sum(m: map<ReqId, nat>): nat
    decreases m.Keys
  {
    if m == map[] then 0 else var k :| k in m; m[k] + Sum(m - {k})
  }

  // Sum is independent of the key the definition picks. Proven here once;
  // implementations call it when they add or remove a hold.
  lemma SumRemove(m: map<ReqId, nat>, k: ReqId)
    requires k in m
    ensures Sum(m) == m[k] + Sum(m - {k})
    decreases m.Keys
  {
    var k0 :| k0 in m && Sum(m) == m[k0] + Sum(m - {k0});
    if k0 != k {
      SumRemove(m - {k0}, k);
      SumRemove(m - {k}, k0);
      assert (m - {k0}) - {k} == (m - {k}) - {k0};
    }
  }

  lemma SumAdd(m: map<ReqId, nat>, k: ReqId, v: nat)
    requires k !in m
    ensures Sum(m[k := v]) == Sum(m) + v
  {
    SumRemove(m[k := v], k);
    assert m[k := v] - {k} == m;
  }

  ghost function Reserved(a: Account): nat { Sum(a.holds) }
  ghost function Available(a: Account): int { a.limit as int - a.posted as int - Reserved(a) as int }

  // ---- state invariant ----------------------------------------------------

  ghost predicate Valid(a: Account)
  {
    && a.posted + Reserved(a) <= a.limit                                        // [INV1] never over limit
    && (forall id :: id in a.holds ==> id in a.status && a.status[id] == Auth)  // [P2]  a hold exists only while Auth(orized)
    && (forall id :: id in a.status && a.status[id] == Auth ==> id in a.holds)  // [P2'] Auth(orized) means a live hold
  }

  // ---- obligations --------------------------------------------------------

  trait {:termination false} Authorizer {   // see tcb.yaml: cross-module termination

    // Decide one authorization request atomically.
    // Precondition: the request is new to this account (its "Pending" condition).
    method Decide(a: Account, r: Request) returns (d: Decision, a': Account)
      requires Valid(a)
      requires r.id !in a.status
      ensures Valid(a')                                                                    // [INV1] preserved
      ensures a'.limit == a.limit && a'.posted == a.posted                                // [F]    Decide touches only holds and status
      ensures a'.status.Keys == a.status.Keys + {r.id}                                     // [F]    exactly this request is decided
      ensures r.id in a'.status                                                           // [D]    the request is decided
      ensures d == Authorized <==> a'.status[r.id] == Auth                          // [D]
      ensures d == Declined   <==> a'.status[r.id] == Decl                            // [D]
      ensures forall id :: id in a.status ==> id in a'.status && a'.status[id] == a.status[id]  // [P3] earlier decisions are terminal
      ensures r.amount as int >  Available(a) ==> d == Declined   && a'.holds == a.holds  // [P1] over limit: decline, reserve nothing
      ensures r.amount as int <= Available(a) ==> d == Authorized && a'.holds == a.holds[r.id := r.amount]  // [P0] within limit (equality included): authorize and reserve
  }

  // Release an authorized hold (void). Included so that P2/P3 are exercised by a second operation.
  trait {:termination false} Releaser {
    method Release(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')                                                                    // [INV1]
      ensures a'.limit == a.limit && a'.posted == a.posted                                // [F]
      ensures a'.holds == a.holds - {id}                                                  // [R1] the hold is gone
      ensures a'.status == a.status[id := Rel]                                       // [R2] status moves to Released; nothing else changes
  }
}
