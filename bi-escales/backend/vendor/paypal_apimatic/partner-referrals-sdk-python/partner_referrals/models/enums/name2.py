from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name2(str, Enum):
    NOT_AUTHORIZED = "NOT_AUTHORIZED"

    __str__ = str.__str__


Name2OrStr: TypeAlias = Annotated[Name2 | str, open_enum_validator(Name2)]
