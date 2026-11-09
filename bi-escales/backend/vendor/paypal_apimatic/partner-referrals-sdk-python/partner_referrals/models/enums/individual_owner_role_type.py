from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class IndividualOwnerRoleType(str, Enum):
    """Role of the person party played in the account."""

    PRIMARY = "PRIMARY"

    __str__ = str.__str__


IndividualOwnerRoleTypeOrStr: TypeAlias = Annotated[
    IndividualOwnerRoleType | str, open_enum_validator(IndividualOwnerRoleType)
]
