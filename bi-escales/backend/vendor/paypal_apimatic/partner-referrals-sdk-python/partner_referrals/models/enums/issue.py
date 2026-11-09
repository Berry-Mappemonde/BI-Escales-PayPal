from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue(str, Enum):
    INVALID_STRING_LENGTH = "INVALID_STRING_LENGTH"

    __str__ = str.__str__


IssueOrStr: TypeAlias = Annotated[Issue | str, open_enum_validator(Issue)]
