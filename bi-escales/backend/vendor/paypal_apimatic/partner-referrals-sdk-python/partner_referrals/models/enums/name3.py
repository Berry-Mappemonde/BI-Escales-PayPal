from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name3(str, Enum):
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    __str__ = str.__str__


Name3OrStr: TypeAlias = Annotated[Name3 | str, open_enum_validator(Name3)]
