from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class DocumentType(str, Enum):
    """The type of documents."""

    SOCIAL_SECURITY_NUMBER = "SOCIAL_SECURITY_NUMBER"
    EMPLOYMENT_IDENTIFICATION_NUMBER = "EMPLOYMENT_IDENTIFICATION_NUMBER"
    TAX_IDENTIFICATION_NUMBER = "TAX_IDENTIFICATION_NUMBER"
    PASSPORT_NUMBER = "PASSPORT_NUMBER"
    PENSION_FUND_ID = "PENSION_FUND_ID"
    MEDICAL_INSURANCE_ID = "MEDICAL_INSURANCE_ID"
    CNPJ = "CNPJ"
    CPF = "CPF"
    PAN = "PAN"
    NATIONAL_ID_CARD = "NATIONAL_ID_CARD"

    __str__ = str.__str__


DocumentTypeOrStr: TypeAlias = Annotated[DocumentType | str, open_enum_validator(DocumentType)]
