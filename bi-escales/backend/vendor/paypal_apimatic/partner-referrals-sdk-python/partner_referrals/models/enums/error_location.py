from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class ErrorLocation(str, Enum):
    """The location of the field that caused the error. Value is ``body``, ``path``, or ``query``."""

    BODY = "body"
    PATH = "path"
    QUERY = "query"

    __str__ = str.__str__


ErrorLocationOrStr: TypeAlias = Annotated[ErrorLocation | str, open_enum_validator(ErrorLocation)]
