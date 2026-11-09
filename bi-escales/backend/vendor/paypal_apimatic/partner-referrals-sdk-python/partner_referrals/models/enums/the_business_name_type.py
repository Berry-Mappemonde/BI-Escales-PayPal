from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class TheBusinessNameType(str, Enum):
    """Business name type"""

    DOING_BUSINESS_AS = "DOING_BUSINESS_AS"
    LEGAL_NAME = "LEGAL_NAME"

    __str__ = str.__str__


TheBusinessNameTypeOrStr: TypeAlias = Annotated[TheBusinessNameType | str, open_enum_validator(TheBusinessNameType)]
