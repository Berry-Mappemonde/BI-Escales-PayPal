from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .business_address_detail import BusinessAddressDetail, BusinessAddressDetailDict
from .business_document import BusinessDocument, BusinessDocumentDict
from .business_incorporation import BusinessIncorporation, BusinessIncorporationDict
from .business_industry import BusinessIndustry, BusinessIndustryDict
from .business_name_detail import BusinessNameDetail, BusinessNameDetailDict
from .business_phone_detail import BusinessPhoneDetail, BusinessPhoneDetailDict
from .business_type_information import BusinessTypeInformation, BusinessTypeInformationDict
from .email_of_a_person_orbusiness import EmailOfAPersonOrbusiness, EmailOfAPersonOrbusinessDict


class Business(SdkBaseModel):
    business_type: Optional[BusinessTypeInformation] = UNSET
    """The type and subtype of the business."""

    business_industry: Optional[BusinessIndustry] = UNSET
    """The category, subcategory and MCC code of the business."""

    business_incorporation: Optional[BusinessIncorporation] = UNSET
    """Business incorporation information."""

    names: Optional[list[BusinessNameDetail]] = UNSET
    """Name of the business."""

    emails: Optional[list[EmailOfAPersonOrbusiness]] = UNSET
    """Email addresses of the business."""

    website: Optional[str] = UNSET
    """Website of the business."""

    addresses: Optional[list[BusinessAddressDetail]] = UNSET
    """List of addresses associated with the business entity."""

    phones: Optional[list[BusinessPhoneDetail]] = UNSET
    """List of phone number associated with the business."""

    documents: Optional[list[BusinessDocument]] = UNSET
    """Business Party related Document data collected from the customer.. For example SSN, ITIN, Business registration
    number that were collected from the user."""


class BusinessDict(TypedDict):
    business_type: NotRequired[BusinessTypeInformationDict]
    business_industry: NotRequired[BusinessIndustryDict]
    business_incorporation: NotRequired[BusinessIncorporationDict]
    names: NotRequired[list[BusinessNameDetailDict]]
    emails: NotRequired[list[EmailOfAPersonOrbusinessDict]]
    website: NotRequired[str]
    addresses: NotRequired[list[BusinessAddressDetailDict]]
    phones: NotRequired[list[BusinessPhoneDetailDict]]
    documents: NotRequired[list[BusinessDocumentDict]]
