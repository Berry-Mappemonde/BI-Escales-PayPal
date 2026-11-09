from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .birth_details import BirthDetails, BirthDetailsDict
from .person_address_detail import PersonAddressDetail, PersonAddressDetailDict
from .person_document import PersonDocument, PersonDocumentDict
from .person_name import PersonName, PersonNameDict
from .person_phone_detail import PersonPhoneDetail, PersonPhoneDetailDict


class Person(SdkBaseModel):
    """Details of the person or party."""

    id: Optional[str] = UNSET
    """The encrypted party ID."""

    names: Optional[list[PersonName]] = UNSET
    """The name of the person."""

    citizenship: Optional[str] = UNSET
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""

    addresses: Optional[list[PersonAddressDetail]] = UNSET
    """The list of addresses associated with the person."""

    phones: Optional[list[PersonPhoneDetail]] = UNSET
    """The list of phone numbers associated with the person."""

    birth_details: Optional[BirthDetails] = UNSET
    """Date of birth data provided by the user"""

    documents: Optional[list[PersonDocument]] = UNSET
    """A person's or party's related document data collected from the customer. For example SSN, ITIN, or business
    registration number collected from the user. <blockquote><strong>Note:</strong> This field is not applicable for
    POST `/v2/customer/partner-referrals </docs/api/partner-referrals/v2/#partner-referrals_create>`__ API
    calls.</blockquote>"""


class PersonDict(TypedDict):
    id: NotRequired[str]
    names: NotRequired[list[PersonNameDict]]
    citizenship: NotRequired[str]
    addresses: NotRequired[list[PersonAddressDetailDict]]
    phones: NotRequired[list[PersonPhoneDetailDict]]
    birth_details: NotRequired[BirthDetailsDict]
    documents: NotRequired[list[PersonDocumentDict]]
