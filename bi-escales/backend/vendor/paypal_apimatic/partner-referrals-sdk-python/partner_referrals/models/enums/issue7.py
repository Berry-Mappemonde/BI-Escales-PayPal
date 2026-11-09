from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue7(str, Enum):
    ACCOUNT_STATUS_ERROR = "ACCOUNT_STATUS_ERROR"

    __str__ = str.__str__


Issue7OrStr: TypeAlias = Annotated[Issue7 | str, open_enum_validator(Issue7)]
