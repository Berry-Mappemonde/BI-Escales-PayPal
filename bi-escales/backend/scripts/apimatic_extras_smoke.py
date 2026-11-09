#!/usr/bin/env python3
"""Sandbox smoke for the APIMatic Payouts and Partner Referrals extras.

The operator runs this. It is not part of CI. Required environment variables,
by name only:

- ``ESCALES_APIMATIC_EXTRAS_ENABLED=1``
- ``PAYPAL_ENV=sandbox``
- ``PAYPAL_CLIENT_ID`` and ``PAYPAL_CLIENT_SECRET`` (payout batch)
- ``PAYPAL_PLATFORM_CLIENT_ID`` and ``PAYPAL_PLATFORM_CLIENT_SECRET`` (referral)
- ``APIM9_PAYOUT_RECEIVER`` (sandbox receiver email)

Stdout is one JSON object of ids and statuses. A PayPal 403 (permission
propagation) prints ``{"status":"403_propagation"}`` and exits 0.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.escales.paypal_apimatic_extras import (  # noqa: E402
    ApimaticExtrasDisabledError,
    ApimaticExtrasSandboxRequiredError,
    apimatic_extras_enabled,
    create_partner_referral,
    create_payout_batch,
    get_partner_referral,
    get_payout_batch,
)
from app.escales.paypal_client import PayPalError  # noqa: E402


def main() -> int:
    if not apimatic_extras_enabled():
        _emit({"status": "disabled"})
        return 2
    receiver = _receiver()
    if not receiver:
        _emit({"status": "missing_receiver"})
        return 2
    sender_batch_id = uuid.uuid4().hex
    tracking_id = uuid.uuid4().hex
    try:
        created = create_payout_batch(_payout_body(receiver, sender_batch_id))
        payout_id, _created_status = _payout_id_status(created)
        fetched = get_payout_batch(payout_id)
        referral_created = create_partner_referral(_referral_body(tracking_id))
        referral_id = referral_id_from(referral_created)
        referral_fetched = get_partner_referral(referral_id)
    except PayPalError as exc:
        if exc.status == 403:
            _emit({"status": "403_propagation"})
            return 0
        _emit({"status": str(exc.status)})
        return 1
    except ApimaticExtrasSandboxRequiredError:
        _emit({"status": "sandbox_required"})
        return 2
    except ApimaticExtrasDisabledError:
        _emit({"status": "disabled"})
        return 2
    except SmokeReportError as exc:
        _emit({"status": exc.status})
        return 1
    report = public_report(
        payout_created=created,
        payout_fetched=fetched,
        referral_created=referral_created,
        referral_fetched=referral_fetched,
    )
    _emit(report)
    return 0


def public_report(
    *,
    payout_created: Mapping[str, Any],
    payout_fetched: Mapping[str, Any],
    referral_created: Mapping[str, Any],
    referral_fetched: Mapping[str, Any],
) -> dict[str, str]:
    """Ids and statuses only. Drops links, emails, and token-bearing fields."""
    created_id, created_status = _payout_id_status(payout_created)
    fetched_id, fetched_status = _payout_id_status(payout_fetched)
    referral_id = str(referral_fetched.get("partner_referral_id") or "").strip()
    if referral_id and _sensitive(referral_id):
        raise SmokeReportError("missing_id")
    if not referral_id:
        referral_id = referral_id_from(referral_created)
    referral_status = "READ" if referral_fetched.get("partner_referral_id") else "CREATED"
    return {
        "payout_batch_id": fetched_id or created_id,
        "payout_create_status": created_status,
        "payout_get_status": fetched_status,
        "partner_referral_id": referral_id,
        "partner_referral_status": referral_status,
    }


def referral_id_from(payload: Mapping[str, Any]) -> str:
    """Referral id from ``partner_referral_id`` or the ``self`` link path."""
    direct = payload.get("partner_referral_id")
    if isinstance(direct, str) and direct.strip() and not _sensitive(direct):
        return direct.strip()
    for link in payload.get("links") or []:
        if not isinstance(link, Mapping):
            continue
        if str(link.get("rel") or "").lower() != "self":
            continue
        href = str(link.get("href") or "")
        segment = href.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if segment and not _sensitive(segment):
            return segment
    raise SmokeReportError("missing_id")


class SmokeReportError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _receiver() -> str:
    value = (os.environ.get("APIM9_PAYOUT_RECEIVER") or "").strip()
    if "@" not in value or _sensitive(value):
        return ""
    return value


def _sensitive(value: str) -> bool:
    lowered = value.lower()
    return "bearer " in lowered or "referraltoken=" in lowered or "access_token=" in lowered


def _payout_body(receiver: str, sender_batch_id: str) -> dict[str, Any]:
    return {
        "sender_batch_header": {
            "sender_batch_id": sender_batch_id,
            "recipient_type": "EMAIL",
            "email_subject": "BI Escales sandbox payout",
            "email_message": "Sandbox payout of 1.00 EUR",
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "amount": {"currency": "EUR", "value": "1.00"},
                "receiver": receiver,
                "sender_item_id": sender_batch_id,
                "recipient_wallet": "PAYPAL",
            }
        ],
    }


def _referral_body(tracking_id: str) -> dict[str, Any]:
    return {
        "tracking_id": tracking_id,
        "products": ["EXPRESS_CHECKOUT"],
        "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
        "operations": [
            {
                "operation": "API_INTEGRATION",
                "api_integration_preference": {
                    "rest_api_integration": {
                        "integration_method": "PAYPAL",
                        "integration_type": "THIRD_PARTY",
                        "third_party_details": {"features": ["PAYMENT", "REFUND"]},
                    }
                },
            }
        ],
    }


def _payout_id_status(payload: Mapping[str, Any]) -> tuple[str, str]:
    header = payload.get("batch_header")
    if not isinstance(header, Mapping):
        raise SmokeReportError("missing_id")
    batch_id = str(header.get("payout_batch_id") or "").strip()
    status = str(header.get("batch_status") or "").strip()
    if not batch_id or _sensitive(batch_id):
        raise SmokeReportError("missing_id")
    return batch_id, status


def _emit(payload: Mapping[str, str]) -> None:
    sys.stdout.write(json.dumps(dict(payload), sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    sys.exit(main())
