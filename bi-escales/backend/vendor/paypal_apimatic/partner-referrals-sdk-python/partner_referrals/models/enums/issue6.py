from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue6(str, Enum):
    USER_NOT_FOUND = "USER_NOT_FOUND"

    __str__ = str.__str__


Issue6OrStr: TypeAlias = Annotated[Issue6 | str, open_enum_validator(Issue6)]
