from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Method1(str, Enum):
    """The HTTP method required to make the related call."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"

    __str__ = str.__str__


Method1OrStr: TypeAlias = Annotated[Method1 | str, open_enum_validator(Method1)]
