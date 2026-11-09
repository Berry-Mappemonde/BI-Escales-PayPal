from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description6(str, Enum):
    ACCOUNT_FOR_THIS_PARTNER_ID_DOES_NOT_EXIST = "Account for this Partner ID does not exist."

    __str__ = str.__str__


Description6OrStr: TypeAlias = Annotated[Description6 | str, open_enum_validator(Description6)]
