from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description8(str, Enum):
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""

    THE_VALUE_OF_A_FIELD_IS_EITHER_TOO_SHORT_OR_TOO_LONG = "the value of a field is either too short or too long"

    __str__ = str.__str__


Description8OrStr: TypeAlias = Annotated[Description8 | str, open_enum_validator(Description8)]
