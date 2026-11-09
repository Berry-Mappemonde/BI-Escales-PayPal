from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name5(str, Enum):
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"

    __str__ = str.__str__


Name5OrStr: TypeAlias = Annotated[Name5 | str, open_enum_validator(Name5)]
