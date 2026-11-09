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
    "https://uri.paypal.com/payments/payouts",
    "https://uri.paypal.com/services/payments/payouts-item/reverse",
    "https://uri.paypal.com/services/payments/payout-applications/status",
    "https://uri.paypal.com/services/payments/payout-applications/update-status",
]
"""``https://uri.paypal.com/payments/payouts``: Payout to a list of recipients.
``https://uri.paypal.com/services/payments/payouts-item/reverse``: For reversing a completed payout item.
``https://uri.paypal.com/services/payments/payout-applications/status``: For retrieving payouts application status.
``https://uri.paypal.com/services/payments/payout-applications/update-status``: For updating payouts application
status."""
