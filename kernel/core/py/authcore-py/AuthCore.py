import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_
import AuthSpec as AuthSpec

# Module: AuthCore


class Core(AuthSpec.Authorizer, AuthSpec.Releaser):
    def  __init__(self):
        pass

    def __dafnystr__(self) -> str:
        return "AuthCore.Core"
    def ctor__(self):
        pass
        pass

    def Decide(self, a, r):
        d: AuthSpec.Decision = AuthSpec.Decision.default()()
        a_k: AuthSpec.Account = AuthSpec.Account.default()()
        d_0_reserved_: int
        out0_: int
        out0_ = (self).SumHolds((a).holds)
        d_0_reserved_ = out0_
        d_1_available_: int
        d_1_available_ = (((a).limit) - ((a).posted)) - (d_0_reserved_)
        if ((r).amount) > (d_1_available_):
            d = AuthSpec.Decision_Declined()
            d_2_dt__update__tmp_h0_ = a
            d_3_dt__update_hstatus_h0_ = ((a).status).set((r).id_, AuthSpec.Status_Decl())
            a_k = AuthSpec.Account_Account((d_2_dt__update__tmp_h0_).limit, (d_2_dt__update__tmp_h0_).posted, (d_2_dt__update__tmp_h0_).holds, d_3_dt__update_hstatus_h0_)
        elif True:
            d = AuthSpec.Decision_Authorized()
            d_4_dt__update__tmp_h1_ = a
            d_5_dt__update_hstatus_h1_ = ((a).status).set((r).id_, AuthSpec.Status_Auth())
            d_6_dt__update_hholds_h0_ = ((a).holds).set((r).id_, (r).amount)
            a_k = AuthSpec.Account_Account((d_4_dt__update__tmp_h1_).limit, (d_4_dt__update__tmp_h1_).posted, d_6_dt__update_hholds_h0_, d_5_dt__update_hstatus_h1_)
        return d, a_k

    def Release(self, a, id_):
        a_k: AuthSpec.Account = AuthSpec.Account.default()()
        d_0_dt__update__tmp_h0_ = a
        d_1_dt__update_hstatus_h0_ = ((a).status).set(id_, AuthSpec.Status_Rel())
        d_2_dt__update_hholds_h0_ = ((a).holds) - (_dafny.Set({id_}))
        a_k = AuthSpec.Account_Account((d_0_dt__update__tmp_h0_).limit, (d_0_dt__update__tmp_h0_).posted, d_2_dt__update_hholds_h0_, d_1_dt__update_hstatus_h0_)
        return a_k

    def SumHolds(self, m):
        s: int = int(0)
        if (m) == (_dafny.Map({})):
            s = 0
            return s
        d_0_k_: int
        with _dafny.label("_ASSIGN_SUCH_THAT_d_0"):
            assign_such_that_0_: int
            for assign_such_that_0_ in (m).keys.Elements:
                d_0_k_ = assign_such_that_0_
                if System_.nat._Is(d_0_k_):
                    if (d_0_k_) in (m):
                        raise _dafny.Break("_ASSIGN_SUCH_THAT_d_0")
            raise Exception("assign-such-that search produced no value")
            pass
        d_1_rest_: int
        out0_: int
        out0_ = (self).SumHolds((m) - (_dafny.Set({d_0_k_})))
        d_1_rest_ = out0_
        s = ((m)[d_0_k_]) + (d_1_rest_)
        return s

