import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_
import BookingSpec as BookingSpec

# Module: BookingCore

class default__:
    def  __init__(self):
        pass

    @staticmethod
    def FindBlocker(c, s, e, except_):
        k: int = int(0)
        k = 0
        while (k) < (len(c)):
            if BookingSpec.default__.Blocks((c)[k], s, e, except_):
                return k
            k = (k) + (1)
        k = -1
        return k

    @staticmethod
    def IndexOf(c, id_):
        k: int = int(0)
        k = 0
        while (k) < (len(c)):
            if (((c)[k]).id_) == (id_):
                return k
            k = (k) + (1)
        k = -1
        return k


class Core(BookingSpec.Booker, BookingSpec.Canceller, BookingSpec.Rescheduler):
    def  __init__(self):
        pass

    def __dafnystr__(self) -> str:
        return "BookingCore.Core"
    def ctor__(self):
        pass
        pass

    def Book(self, c, id_, s, e):
        o: BookingSpec.Outcome = BookingSpec.Outcome.default()()
        c_k: _dafny.Seq = _dafny.Seq({})
        if not(BookingSpec.default__.WellFormed(s, e)):
            rhs0_ = BookingSpec.Outcome_Invalid()
            rhs1_ = c
            o = rhs0_
            c_k = rhs1_
            return o, c_k
        d_0_k_: int
        out0_: int
        out0_ = default__.FindBlocker(c, s, e, id_)
        d_0_k_ = out0_
        if (d_0_k_) >= (0):
            rhs2_ = BookingSpec.Outcome_Conflict(((c)[d_0_k_]).id_)
            rhs3_ = c
            o = rhs2_
            c_k = rhs3_
            return o, c_k
        rhs4_ = BookingSpec.Outcome_Accepted()
        rhs5_ = (c) + (_dafny.SeqWithoutIsStrInference([BookingSpec.Slot_Slot(id_, s, e, True)]))
        o = rhs4_
        c_k = rhs5_
        return o, c_k

    def Cancel(self, c, id_):
        ok: bool = False
        c_k: _dafny.Seq = _dafny.Seq({})
        d_0_k_: int
        out0_: int
        out0_ = default__.IndexOf(c, id_)
        d_0_k_ = out0_
        if ((d_0_k_) < (0)) or (not(((c)[d_0_k_]).active)):
            rhs0_ = False
            rhs1_ = c
            ok = rhs0_
            c_k = rhs1_
            return ok, c_k
        def iife0_(_pat_let0_0):
            def iife1_(d_1_dt__update__tmp_h1_):
                def iife2_(_pat_let1_0):
                    def iife3_(d_2_dt__update_hactive_h1_):
                        return BookingSpec.Slot_Slot((d_1_dt__update__tmp_h1_).id_, (d_1_dt__update__tmp_h1_).start, (d_1_dt__update__tmp_h1_).end, d_2_dt__update_hactive_h1_)
                    return iife3_(_pat_let1_0)
                return iife2_(False)
            return iife1_(_pat_let0_0)
        rhs2_ = True
        rhs3_ = (c).set(d_0_k_, iife0_((c)[d_0_k_]))
        ok = rhs2_
        c_k = rhs3_
        return ok, c_k

    def Reschedule(self, c, id_, s, e):
        o: BookingSpec.Outcome = BookingSpec.Outcome.default()()
        c_k: _dafny.Seq = _dafny.Seq({})
        d_0_k_: int
        out0_: int
        out0_ = default__.IndexOf(c, id_)
        d_0_k_ = out0_
        if ((d_0_k_) < (0)) or (not(((c)[d_0_k_]).active)):
            rhs0_ = BookingSpec.Outcome_NotActive()
            rhs1_ = c
            o = rhs0_
            c_k = rhs1_
            return o, c_k
        if not(BookingSpec.default__.WellFormed(s, e)):
            rhs2_ = BookingSpec.Outcome_Invalid()
            rhs3_ = c
            o = rhs2_
            c_k = rhs3_
            return o, c_k
        d_1_b_: int
        out1_: int
        out1_ = default__.FindBlocker(c, s, e, id_)
        d_1_b_ = out1_
        if (d_1_b_) >= (0):
            rhs4_ = BookingSpec.Outcome_Conflict(((c)[d_1_b_]).id_)
            rhs5_ = c
            o = rhs4_
            c_k = rhs5_
            return o, c_k
        pat_let_tv0_ = e
        pat_let_tv1_ = s
        def iife0_(_pat_let2_0):
            def iife1_(d_2_dt__update__tmp_h1_):
                def iife2_(_pat_let3_0):
                    def iife3_(d_3_dt__update_hend_h1_):
                        def iife4_(_pat_let4_0):
                            def iife5_(d_4_dt__update_hstart_h1_):
                                return BookingSpec.Slot_Slot((d_2_dt__update__tmp_h1_).id_, d_4_dt__update_hstart_h1_, d_3_dt__update_hend_h1_, (d_2_dt__update__tmp_h1_).active)
                            return iife5_(_pat_let4_0)
                        return iife4_(pat_let_tv1_)
                    return iife3_(_pat_let3_0)
                return iife2_(pat_let_tv0_)
            return iife1_(_pat_let2_0)
        rhs6_ = BookingSpec.Outcome_Accepted()
        rhs7_ = (c).set(d_0_k_, iife0_((c)[d_0_k_]))
        o = rhs6_
        c_k = rhs7_
        return o, c_k

