from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue8(str, Enum):
    PRODUCT_PPCP_UNAUTHORIZED = "PRODUCT_PPCP_UNAUTHORIZED"

    __str__ = str.__str__


Issue8OrStr: TypeAlias = Annotated[Issue8 | str, open_enum_validator(Issue8)]
