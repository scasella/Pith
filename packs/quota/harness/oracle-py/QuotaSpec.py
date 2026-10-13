import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_

# Module: QuotaSpec

class default__:
    def  __init__(self):
        pass

    @staticmethod
    def ValidConfig(c):
        return (((c).limit) >= (1)) and (((c).window) >= (1))

    @staticmethod
    def Initial():
        return State_State(0, _dafny.SeqWithoutIsStrInference([]))

    @staticmethod
    def Counts(e, k, t, w):
        return ((((e).key) == (k)) and (((e).t) <= (t))) and ((t) < (((e).t) + (w)))

    @staticmethod
    def Used(log, k, t, w):
        d_0___accumulator_ = 0
        while True:
            with _dafny.label():
                if (len(log)) == (0):
                    return (0) + (d_0___accumulator_)
                elif True:
                    d_0___accumulator_ = ((((log)[(len(log)) - (1)]).cost if default__.Counts((log)[(len(log)) - (1)], k, t, w) else 0)) + (d_0___accumulator_)
                    in0_ = _dafny.SeqWithoutIsStrInference((log)[:(len(log)) - (1):])
                    in1_ = k
                    in2_ = t
                    in3_ = w
                    log = in0_
                    k = in1_
                    t = in2_
                    w = in3_
                    raise _dafny.TailCall()
                break

    @staticmethod
    def FitsAt(c, log, k, cost, t):
        return ((default__.Used(log, k, t, (c).window)) + (cost)) <= ((c).limit)

    @staticmethod
    def FitsAfter(c, log, k, cost, now, r):
        return default__.FitsAt(c, log, k, cost, (now) + (r))


class Config:
    @classmethod
    def default(cls, ):
        return lambda: Config_Config(int(0), int(0))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Config(self) -> bool:
        return isinstance(self, Config_Config)

class Config_Config(Config, NamedTuple('Config', [('limit', Any), ('window', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Config.Config({_dafny.string_of(self.limit)}, {_dafny.string_of(self.window)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Config_Config) and self.limit == __o.limit and self.window == __o.window
    def __hash__(self) -> int:
        return super().__hash__()


class Entry:
    @classmethod
    def default(cls, ):
        return lambda: Entry_Entry(_dafny.SeqWithoutIsStrInference(map(_dafny.CodePoint, "")), int(0), int(0))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Entry(self) -> bool:
        return isinstance(self, Entry_Entry)

class Entry_Entry(Entry, NamedTuple('Entry', [('key', Any), ('t', Any), ('cost', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Entry.Entry({self.key.VerbatimString(True)}, {_dafny.string_of(self.t)}, {_dafny.string_of(self.cost)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Entry_Entry) and self.key == __o.key and self.t == __o.t and self.cost == __o.cost
    def __hash__(self) -> int:
        return super().__hash__()


class State:
    @classmethod
    def default(cls, ):
        return lambda: State_State(int(0), _dafny.Seq({}))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_State(self) -> bool:
        return isinstance(self, State_State)

class State_State(State, NamedTuple('State', [('clock', Any), ('log', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.State.State({_dafny.string_of(self.clock)}, {_dafny.string_of(self.log)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, State_State) and self.clock == __o.clock and self.log == __o.log
    def __hash__(self) -> int:
        return super().__hash__()


class Option:
    @classmethod
    def default(cls, ):
        return lambda: Option_None()
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_None(self) -> bool:
        return isinstance(self, Option_None)
    @property
    def is_Some(self) -> bool:
        return isinstance(self, Option_Some)

class Option_None(Option, NamedTuple('None_', [])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Option.None'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Option_None)
    def __hash__(self) -> int:
        return super().__hash__()

class Option_Some(Option, NamedTuple('Some', [('value', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Option.Some({_dafny.string_of(self.value)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Option_Some) and self.value == __o.value
    def __hash__(self) -> int:
        return super().__hash__()


class Decision:
    @classmethod
    def default(cls, ):
        return lambda: Decision_Granted(int(0))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Granted(self) -> bool:
        return isinstance(self, Decision_Granted)
    @property
    def is_Denied(self) -> bool:
        return isinstance(self, Decision_Denied)
    @property
    def is_Regressed(self) -> bool:
        return isinstance(self, Decision_Regressed)

class Decision_Granted(Decision, NamedTuple('Granted', [('remaining', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Decision.Granted({_dafny.string_of(self.remaining)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Decision_Granted) and self.remaining == __o.remaining
    def __hash__(self) -> int:
        return super().__hash__()

class Decision_Denied(Decision, NamedTuple('Denied', [('remaining', Any), ('retryAfter', Any)])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Decision.Denied({_dafny.string_of(self.remaining)}, {_dafny.string_of(self.retryAfter)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Decision_Denied) and self.remaining == __o.remaining and self.retryAfter == __o.retryAfter
    def __hash__(self) -> int:
        return super().__hash__()

class Decision_Regressed(Decision, NamedTuple('Regressed', [])):
    def __dafnystr__(self) -> str:
        return f'QuotaSpec.Decision.Regressed'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Decision_Regressed)
    def __hash__(self) -> int:
        return super().__hash__()


class Acquirer:
    pass
    def Acquire(self, c, s, k, cost, now):
        pass


class Peeker:
    pass
    def Peek(self, c, s, k, now):
        pass

