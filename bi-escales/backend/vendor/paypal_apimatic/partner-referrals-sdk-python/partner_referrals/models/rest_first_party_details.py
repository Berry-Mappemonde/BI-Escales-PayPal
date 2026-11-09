from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel
from .enums.rest_endpoint_features import RestEndpointFeaturesOrStr


class RestFirstPartyDetails(SdkBaseModel):
    """The integration details for PayPal first party REST endpoints."""

    features: list[RestEndpointFeaturesOrStr]
    """An array of features that partner can access, or use, in PayPal on behalf of the seller. The seller grants
    permission for these features to the partner."""

    seller_nonce: str
    """S256 - The code verifier must be high-entropy cryptographic random string with a byte length of 43-128 range."""


class RestFirstPartyDetailsDict(TypedDict):
    features: list[RestEndpointFeaturesOrStr]
    seller_nonce: str
