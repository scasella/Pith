// AuthCore.dfy — an implementation submitted against the template.
// It may include spec/AuthSpec.dfy but may not modify it.
include "../spec/AuthSpec.dfy"

module AuthCore {
  import opened AuthSpec

  class Core extends Authorizer, Releaser {

    constructor () {}

    method Decide(a: Account, r: Request) returns (d: Decision, a': Account)
      requires Valid(a)
      requires r.id !in a.status
      ensures Valid(a')
      ensures a'.limit == a.limit && a'.posted == a.posted
      ensures a'.status.Keys == a.status.Keys + {r.id}
      ensures r.id in a'.status
      ensures d == Authorized <==> a'.status[r.id] == Auth
      ensures d == Declined   <==> a'.status[r.id] == Decl
      ensures forall id :: id in a.status ==> id in a'.status && a'.status[id] == a.status[id]
      ensures r.amount as int >  Available(a) ==> d == Declined   && a'.holds == a.holds
      ensures r.amount as int <= Available(a) ==> d == Authorized && a'.holds == a.holds[r.id := r.amount]
    {
      // Executable availability: Reserved is ghost, so the implementation keeps a
      // running total it can prove equal to Sum(holds).
      var reserved := SumHolds(a.holds);
      var available: int := a.limit as int - a.posted as int - reserved as int;
      if r.amount as int > available {
        d  := Declined;
        a' := a.(status := a.status[r.id := Decl]);
      } else {
        SumAdd(a.holds, r.id, r.amount);
        d  := Authorized;
        a' := a.(holds := a.holds[r.id := r.amount], status := a.status[r.id := Auth]);
      }
    }

    method Release(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')
      ensures a'.limit == a.limit && a'.posted == a.posted
      ensures a'.holds == a.holds - {id}
      ensures a'.status == a.status[id := Rel]
    {
      SumRemove(a.holds, id);
      a' := a.(holds := a.holds - {id}, status := a.status[id := Rel]);
    }

    // Compiled sum over the holds map, proven equal to the ghost Sum.
    method SumHolds(m: map<ReqId, nat>) returns (s: nat)
      ensures s == Sum(m)
      decreases m.Keys
    {
      if m == map[] { return 0; }
      var k :| k in m;
      var rest := SumHolds(m - {k});
      SumRemove(m, k);
      s := m[k] + rest;
    }
  }
}
