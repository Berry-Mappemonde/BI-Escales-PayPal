from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name4(str, Enum):
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"

    __str__ = str.__str__


Name4OrStr: TypeAlias = Annotated[Name4 | str, open_enum_validator(Name4)]
