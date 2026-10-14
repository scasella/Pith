import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_
import QuotaSpec as QuotaSpec

# Module: QuotaCore

class default__:
    def  __init__(self):
        pass

    @staticmethod
    def ComputeUsed(log, k, t, w):
        u: int = int(0)
        u = 0
        d_0_i_: int
        d_0_i_ = 0
        while (d_0_i_) < (len(log)):
            if QuotaSpec.default__.Counts((log)[d_0_i_], k, t, w):
                u = (u) + (((log)[d_0_i_]).cost)
            d_0_i_ = (d_0_i_) + (1)
        return u

    @staticmethod
    def EarliestFit(c, log, k, cost, now):
        r: int = int(0)
        r = 1
        d_0_u_: int
        out0_: int
        out0_ = default__.ComputeUsed(log, k, (now) + (r), (c).window)
        d_0_u_ = out0_
        while ((d_0_u_) + (cost)) > (QuotaSpec.default__.LimitOf(c, k)):
            r = (r) + (1)
            out1_: int
            out1_ = default__.ComputeUsed(log, k, (now) + (r), (c).window)
            d_0_u_ = out1_
        return r


class Core(QuotaSpec.Acquirer, QuotaSpec.Peeker, QuotaSpec.LimitReporter):
    def  __init__(self):
        pass

    def __dafnystr__(self) -> str:
        return "QuotaCore.Core"
    def ctor__(self):
        pass
        pass

    def Acquire(self, c, s, k, cost, now):
        d: QuotaSpec.Decision = QuotaSpec.Decision.default()()
        s_k: QuotaSpec.State = QuotaSpec.State.default()()
        if (now) < ((s).clock):
            rhs0_ = QuotaSpec.Decision_Regressed()
            rhs1_ = s
            d = rhs0_
            s_k = rhs1_
            return d, s_k
        d_0_lim_: int
        d_0_lim_ = QuotaSpec.default__.LimitOf(c, k)
        d_1_u_: int
        out0_: int
        out0_ = default__.ComputeUsed((s).log, k, now, (c).window)
        d_1_u_ = out0_
        if ((d_1_u_) + (cost)) <= (d_0_lim_):
            d = QuotaSpec.Decision_Granted(((d_0_lim_) - (d_1_u_)) - (cost))
            s_k = QuotaSpec.State_State(now, ((s).log) + (_dafny.SeqWithoutIsStrInference([QuotaSpec.Entry_Entry(k, now, cost)])))
        elif (cost) > (d_0_lim_):
            d = QuotaSpec.Decision_Denied((d_0_lim_) - (d_1_u_), QuotaSpec.Option_None())
            s_k = QuotaSpec.State_State(now, (s).log)
        elif True:
            d_2_r_: int
            out1_: int
            out1_ = default__.EarliestFit(c, (s).log, k, cost, now)
            d_2_r_ = out1_
            d = QuotaSpec.Decision_Denied((d_0_lim_) - (d_1_u_), QuotaSpec.Option_Some(d_2_r_))
            s_k = QuotaSpec.State_State(now, (s).log)
        return d, s_k

    def Peek(self, c, s, k, now):
        regressed: bool = False
        remaining: int = int(0)
        s_k: QuotaSpec.State = QuotaSpec.State.default()()
        if (now) < ((s).clock):
            rhs0_ = True
            rhs1_ = 0
            rhs2_ = s
            regressed = rhs0_
            remaining = rhs1_
            s_k = rhs2_
            return regressed, remaining, s_k
        d_0_u_: int
        out0_: int
        out0_ = default__.ComputeUsed((s).log, k, now, (c).window)
        d_0_u_ = out0_
        rhs3_ = False
        rhs4_ = (QuotaSpec.default__.LimitOf(c, k)) - (d_0_u_)
        rhs5_ = QuotaSpec.State_State(now, (s).log)
        regressed = rhs3_
        remaining = rhs4_
        s_k = rhs5_
        return regressed, remaining, s_k
        return regressed, remaining, s_k

    def LimitFor(self, c, k):
        l: int = int(0)
        l = QuotaSpec.default__.LimitOf(c, k)
        return l

