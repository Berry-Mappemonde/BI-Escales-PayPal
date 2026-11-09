from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel


class BusinessIndustry(SdkBaseModel):
    """The category, subcategory and MCC code of the business."""

    category: str
    """The customer's business category code. PayPal uses industry standard seller category codes."""

    mcc_code: str
    """The customer's business seller category code. PayPal uses industry standard seller category codes."""

    subcategory: str
    """The customer's business subcategory code. PayPal uses industry standard seller subcategory codes."""


class BusinessIndustryDict(TypedDict):
    category: str
    mcc_code: str
    subcategory: str
