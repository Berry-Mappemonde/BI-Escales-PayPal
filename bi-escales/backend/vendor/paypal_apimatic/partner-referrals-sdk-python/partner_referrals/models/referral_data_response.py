from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .customer_data import CustomerData, CustomerDataDict
from .link_description import LinkDescription, LinkDescriptionDict


class ReferralDataResponse(SdkBaseModel):
    """The share referral data response."""

    partner_referral_id: Optional[str] = UNSET
    """The ID to access the customer's data shared by the partner with PayPal."""

    submitter_payer_id: Optional[str] = UNSET
    """The payer ID of the partner who shared the referral data."""

    submitter_client_id: Optional[str] = UNSET
    """The client ID of the partner who shared the referral data. This cliend ID will be returned only when the caller
    is determined as an internal partner, which means the scope of the caller's security context only have
    "https://uri.paypal.com/services/customer/partner-referrals", For more information, see <a
    href="https://github.paypal.com/Customers-R/partnselleronbnodeserv/blob/b0a631c43e80a4dd43d34c01f479c272b3287796/src/helpers/securityContextHelpers.js#L143">Api
    Actor type in Typhoon service</a>."""

    referral_data: Optional[CustomerData] = UNSET
    """The customer's referral data that partners share with PayPal."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </docs/api/overview/#hateoas-links>`__."""


class ReferralDataResponseDict(TypedDict):
    partner_referral_id: NotRequired[str]
    submitter_payer_id: NotRequired[str]
    submitter_client_id: NotRequired[str]
    referral_data: NotRequired[CustomerDataDict]
    links: NotRequired[list[LinkDescriptionDict]]
