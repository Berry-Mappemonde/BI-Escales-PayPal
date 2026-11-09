from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name7(str, Enum):
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

    __str__ = str.__str__


Name7OrStr: TypeAlias = Annotated[Name7 | str, open_enum_validator(Name7)]
