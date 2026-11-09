from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name8(str, Enum):
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    __str__ = str.__str__


Name8OrStr: TypeAlias = Annotated[Name8 | str, open_enum_validator(Name8)]
