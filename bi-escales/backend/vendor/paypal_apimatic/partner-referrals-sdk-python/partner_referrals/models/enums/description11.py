from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description11(str, Enum):
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""

    ACCOUNT_FOR_THIS_PARTNER_ID_DOES_NOT_EXIST = "Account for this Partner ID does not exist."

    __str__ = str.__str__


Description11OrStr: TypeAlias = Annotated[Description11 | str, open_enum_validator(Description11)]
