from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class AccountType(str, Enum):
    """The type of bank account."""

    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"

    __str__ = str.__str__


AccountTypeOrStr: TypeAlias = Annotated[AccountType | str, open_enum_validator(AccountType)]
