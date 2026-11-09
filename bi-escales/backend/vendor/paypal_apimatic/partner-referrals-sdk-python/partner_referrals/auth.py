from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .core import AsyncAuthScheme, AuthScheme


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthSchemes:
    oauth2: AuthScheme


@dataclass(frozen=True, slots=True, kw_only=True)
class AsyncAuthSchemes:
    oauth2: AsyncAuthScheme


Oauth2Scope: TypeAlias = Literal[
    "https://uri.paypal.com/services/customer/partner",
    "https://uri.paypal.com/services/customer/partner-referrals/readwrite",
    "https://uri.paypal.com/services/customer/partner-referrals",
]
"""``https://uri.paypal.com/services/customer/partner``: Manage seller resources.
``https://uri.paypal.com/services/customer/partner-referrals/readwrite``: Manage external referral data with PayPal.
``https://uri.paypal.com/services/customer/partner-referrals``: Manage referral data shared by Partner with PayPal. To
be used by only internal apps."""
