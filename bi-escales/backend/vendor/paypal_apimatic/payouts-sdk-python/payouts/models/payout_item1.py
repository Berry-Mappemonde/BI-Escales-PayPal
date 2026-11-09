from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, RFC3339DateTime, SdkBaseModel
from .currency import Currency, CurrencyDict
from .currency_conversion_resource import CurrencyConversionResource, CurrencyConversionResourceDict
from .enums.transaction_status import TransactionStatusOrStr
from .error import Error, ErrorDict
from .link_description import LinkDescription, LinkDescriptionDict
from .payout_item_detail import PayoutItemDetail, PayoutItemDetailDict


class PayoutItem1(SdkBaseModel):
    """The payout item status and other details."""

    payout_item_id: str
    """The ID for the payout item. Viewable when you show details for a payout."""

    transaction_id: Optional[str] = UNSET
    """The PayPal-generated ID for the transaction."""

    activity_id: Optional[str] = UNSET
    """The unique PayPal-generated common ID created to link sender side and receiver side transaction. Used for
    tracking."""

    transaction_status: Optional[TransactionStatusOrStr] = UNSET
    """The item transaction status.<blockquote><strong>Note:</strong> For
    <code>POST/v1/payments/payouts-item/{payout_item_id}/cancel</code>, the only possible
    <code>transaction_status</code> value is <code>RETURNED</code>.</blockquote>"""

    payout_item_fee: Optional[Currency] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    payout_batch_id: str
    """The PayPal-generated ID for the payout."""

    payout_item: PayoutItemDetail
    """The details for a sender-created payout to a single recipient."""

    currency_conversion: Optional[CurrencyConversionResource] = UNSET
    """The currency conversion resource."""

    time_processed: Optional[RFC3339DateTime] = UNSET
    """The date and time when this item was last processed, in `Internet date and time format
    <https://tools.ietf.org/html/rfc3339#section-5.6>`__."""

    errors: Optional[Error] = UNSET
    """The error details."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </api/rest/responses/#hateoas-links>`__."""


class PayoutItem1Dict(TypedDict):
    payout_item_id: str
    transaction_id: NotRequired[str]
    activity_id: NotRequired[str]
    transaction_status: NotRequired[TransactionStatusOrStr]
    payout_item_fee: NotRequired[CurrencyDict]
    payout_batch_id: str
    payout_item: PayoutItemDetailDict
    currency_conversion: NotRequired[CurrencyConversionResourceDict]
    time_processed: NotRequired[RFC3339DateTime]
    errors: NotRequired[ErrorDict]
    links: NotRequired[list[LinkDescriptionDict]]
