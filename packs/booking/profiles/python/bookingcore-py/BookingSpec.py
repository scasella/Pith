import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_

# Module: BookingSpec

class default__:
    def  __init__(self):
        pass

    @staticmethod
    def WellFormed(s, e):
        return (s) < (e)

    @staticmethod
    def Overlaps(s1, e1, s2, e2):
        return ((s1) < (e2)) and ((s2) < (e1))

    @staticmethod
    def Near(s1, e1, s2, e2, g):
        return default__.Overlaps(s1, (e1) + (g), s2, (e2) + (g))

    @staticmethod
    def Blocks(x, s, e, except_, g):
        return (((x).active) and (((x).id_) != (except_))) and (default__.Near((x).start, (x).end, s, e, g))

    @staticmethod
    def Free(c, s, e, except_, g):
        def lambda0_(forall_var_0_):
            d_0_i_: int = forall_var_0_
            return not (((0) <= (d_0_i_)) and ((d_0_i_) < (len(c)))) or (not(default__.Blocks((c)[d_0_i_], s, e, except_, g)))

        return _dafny.quantifier(_dafny.IntegerRange(0, len(c)), True, lambda0_)

    @staticmethod
    def Has(c, id_):
        def lambda0_(exists_var_0_):
            d_0_i_: int = exists_var_0_
            return (((0) <= (d_0_i_)) and ((d_0_i_) < (len(c)))) and ((((c)[d_0_i_]).id_) == (id_))

        return _dafny.quantifier(_dafny.IntegerRange(0, len(c)), False, lambda0_)

    @staticmethod
    def IsActive(c, id_):
        def lambda0_(exists_var_0_):
            d_0_i_: int = exists_var_0_
            return ((((0) <= (d_0_i_)) and ((d_0_i_) < (len(c)))) and ((((c)[d_0_i_]).id_) == (id_))) and (((c)[d_0_i_]).active)

        return _dafny.quantifier(_dafny.IntegerRange(0, len(c)), False, lambda0_)


class Slot:
    @classmethod
    def default(cls, ):
        return lambda: Slot_Slot(int(0), int(0), int(0), False)
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Slot(self) -> bool:
        return isinstance(self, Slot_Slot)

class Slot_Slot(Slot, NamedTuple('Slot', [('id_', Any), ('start', Any), ('end', Any), ('active', Any)])):
    def __dafnystr__(self) -> str:
        return f'BookingSpec.Slot.Slot({_dafny.string_of(self.id_)}, {_dafny.string_of(self.start)}, {_dafny.string_of(self.end)}, {_dafny.string_of(self.active)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Slot_Slot) and self.id_ == __o.id_ and self.start == __o.start and self.end == __o.end and self.active == __o.active
    def __hash__(self) -> int:
        return super().__hash__()


class Outcome:
    @classmethod
    def default(cls, ):
        return lambda: Outcome_Accepted()
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Accepted(self) -> bool:
        return isinstance(self, Outcome_Accepted)
    @property
    def is_Conflict(self) -> bool:
        return isinstance(self, Outcome_Conflict)
    @property
    def is_Invalid(self) -> bool:
        return isinstance(self, Outcome_Invalid)
    @property
    def is_NotActive(self) -> bool:
        return isinstance(self, Outcome_NotActive)

class Outcome_Accepted(Outcome, NamedTuple('Accepted', [])):
    def __dafnystr__(self) -> str:
        return f'BookingSpec.Outcome.Accepted'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Outcome_Accepted)
    def __hash__(self) -> int:
        return super().__hash__()

class Outcome_Conflict(Outcome, NamedTuple('Conflict', [('with_', Any)])):
    def __dafnystr__(self) -> str:
        return f'BookingSpec.Outcome.Conflict({_dafny.string_of(self.with_)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Outcome_Conflict) and self.with_ == __o.with_
    def __hash__(self) -> int:
        return super().__hash__()

class Outcome_Invalid(Outcome, NamedTuple('Invalid', [])):
    def __dafnystr__(self) -> str:
        return f'BookingSpec.Outcome.Invalid'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Outcome_Invalid)
    def __hash__(self) -> int:
        return super().__hash__()

class Outcome_NotActive(Outcome, NamedTuple('NotActive', [])):
    def __dafnystr__(self) -> str:
        return f'BookingSpec.Outcome.NotActive'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Outcome_NotActive)
    def __hash__(self) -> int:
        return super().__hash__()


class Booker:
    pass
    def Book(self, c, g, id_, s, e):
        pass


class Canceller:
    pass
    def Cancel(self, c, g, id_):
        pass


class Rescheduler:
    pass
    def Reschedule(self, c, g, id_, s, e):
        pass

