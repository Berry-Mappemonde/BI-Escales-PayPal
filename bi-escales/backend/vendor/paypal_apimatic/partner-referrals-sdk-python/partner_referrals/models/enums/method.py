from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Method(str, Enum):
    """The HTTP method required to make the related call."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    CONNECT = "CONNECT"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"

    __str__ = str.__str__


MethodOrStr: TypeAlias = Annotated[Method | str, open_enum_validator(Method)]
