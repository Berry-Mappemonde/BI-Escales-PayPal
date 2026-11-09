from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class FundingSource(str, Enum):
    """Identifies a funding source type."""

    BALANCE = "BALANCE"

    __str__ = str.__str__


FundingSourceOrStr: TypeAlias = Annotated[FundingSource | str, open_enum_validator(FundingSource)]
