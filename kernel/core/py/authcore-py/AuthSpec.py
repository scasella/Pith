import sys
from typing import Callable, Any, TypeVar, NamedTuple
from math import floor
from itertools import count

import module_ as module_
import _dafny as _dafny
import System_ as System_

# Module: AuthSpec


class Decision:
    @_dafny.classproperty
    def AllSingletonConstructors(cls):
        return [Decision_Authorized(), Decision_Declined()]
    @classmethod
    def default(cls, ):
        return lambda: Decision_Authorized()
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Authorized(self) -> bool:
        return isinstance(self, Decision_Authorized)
    @property
    def is_Declined(self) -> bool:
        return isinstance(self, Decision_Declined)

class Decision_Authorized(Decision, NamedTuple('Authorized', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Decision.Authorized'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Decision_Authorized)
    def __hash__(self) -> int:
        return super().__hash__()

class Decision_Declined(Decision, NamedTuple('Declined', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Decision.Declined'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Decision_Declined)
    def __hash__(self) -> int:
        return super().__hash__()


class Status:
    @_dafny.classproperty
    def AllSingletonConstructors(cls):
        return [Status_Auth(), Status_Decl(), Status_Rel(), Status_Post()]
    @classmethod
    def default(cls, ):
        return lambda: Status_Auth()
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Auth(self) -> bool:
        return isinstance(self, Status_Auth)
    @property
    def is_Decl(self) -> bool:
        return isinstance(self, Status_Decl)
    @property
    def is_Rel(self) -> bool:
        return isinstance(self, Status_Rel)
    @property
    def is_Post(self) -> bool:
        return isinstance(self, Status_Post)

class Status_Auth(Status, NamedTuple('Auth', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Status.Auth'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Status_Auth)
    def __hash__(self) -> int:
        return super().__hash__()

class Status_Decl(Status, NamedTuple('Decl', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Status.Decl'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Status_Decl)
    def __hash__(self) -> int:
        return super().__hash__()

class Status_Rel(Status, NamedTuple('Rel', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Status.Rel'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Status_Rel)
    def __hash__(self) -> int:
        return super().__hash__()

class Status_Post(Status, NamedTuple('Post', [])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Status.Post'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Status_Post)
    def __hash__(self) -> int:
        return super().__hash__()


class Request:
    @classmethod
    def default(cls, ):
        return lambda: Request_Request(int(0), int(0))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Request(self) -> bool:
        return isinstance(self, Request_Request)

class Request_Request(Request, NamedTuple('Request', [('id_', Any), ('amount', Any)])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Request.Request({_dafny.string_of(self.id_)}, {_dafny.string_of(self.amount)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Request_Request) and self.id_ == __o.id_ and self.amount == __o.amount
    def __hash__(self) -> int:
        return super().__hash__()


class Account:
    @classmethod
    def default(cls, ):
        return lambda: Account_Account(int(0), int(0), _dafny.Map({}), _dafny.Map({}))
    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)
    @property
    def is_Account(self) -> bool:
        return isinstance(self, Account_Account)

class Account_Account(Account, NamedTuple('Account', [('limit', Any), ('posted', Any), ('holds', Any), ('status', Any)])):
    def __dafnystr__(self) -> str:
        return f'AuthSpec.Account.Account({_dafny.string_of(self.limit)}, {_dafny.string_of(self.posted)}, {_dafny.string_of(self.holds)}, {_dafny.string_of(self.status)})'
    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Account_Account) and self.limit == __o.limit and self.posted == __o.posted and self.holds == __o.holds and self.status == __o.status
    def __hash__(self) -> int:
        return super().__hash__()


class Authorizer:
    pass
    def Decide(self, a, r):
        pass


class Releaser:
    pass
    def Release(self, a, id_):
        pass

