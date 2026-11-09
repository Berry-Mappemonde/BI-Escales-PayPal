from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue4(str, Enum):
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"

    __str__ = str.__str__


Issue4OrStr: TypeAlias = Annotated[Issue4 | str, open_enum_validator(Issue4)]
