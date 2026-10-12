import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_
import AuthSpec as AuthSpec
import PostingSpec as PostingSpec

# Module: PostingCore


class Poster(PostingSpec.Capturer):
    def  __init__(self):
        pass

    def __dafnystr__(self) -> str:
        return "PostingCore.Poster"
    def ctor__(self):
        pass
        pass

    def Capture(self, a, id_):
        a_k: AuthSpec.Account = AuthSpec.Account.default()()
        d_0_dt__update__tmp_h0_ = a
        d_1_dt__update_hstatus_h0_ = ((a).status).set(id_, AuthSpec.Status_Post())
        d_2_dt__update_hposted_h0_ = ((a).posted) + (((a).holds)[id_])
        d_3_dt__update_hholds_h0_ = ((a).holds) - (_dafny.Set({id_}))
        a_k = AuthSpec.Account_Account((d_0_dt__update__tmp_h0_).limit, d_2_dt__update_hposted_h0_, d_3_dt__update_hholds_h0_, d_1_dt__update_hstatus_h0_)
        return a_k

