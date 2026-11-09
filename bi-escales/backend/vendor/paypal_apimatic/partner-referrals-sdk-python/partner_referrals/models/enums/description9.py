from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description9(str, Enum):
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""

    THIS_API_CALL_IS_NOT_AUTHORIZED = "This API call is not authorized"

    __str__ = str.__str__


Description9OrStr: TypeAlias = Annotated[Description9 | str, open_enum_validator(Description9)]
