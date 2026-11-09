from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name1(str, Enum):
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"

    __str__ = str.__str__


Name1OrStr: TypeAlias = Annotated[Name1 | str, open_enum_validator(Name1)]
