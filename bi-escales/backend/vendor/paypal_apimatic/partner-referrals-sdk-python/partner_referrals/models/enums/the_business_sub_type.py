from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class TheBusinessSubType(str, Enum):
    """Sub classification of the business type"""

    ASSO_TYPE_INCORPORATED = "ASSO_TYPE_INCORPORATED"
    ASSO_TYPE_NON_INCORPORATED = "ASSO_TYPE_NON_INCORPORATED"
    GOVT_TYPE_ENTITY = "GOVT_TYPE_ENTITY"
    GOVT_TYPE_EMANATION = "GOVT_TYPE_EMANATION"
    GOVT_TYPE_ESTD_COMM = "GOVT_TYPE_ESTD_COMM"
    GOVT_TYPE_ESTD_FC = "GOVT_TYPE_ESTD_FC"
    GOVT_TYPE_ESTD_ST_TR = "GOVT_TYPE_ESTD_ST_TR"

    __str__ = str.__str__


TheBusinessSubTypeOrStr: TypeAlias = Annotated[TheBusinessSubType | str, open_enum_validator(TheBusinessSubType)]
