"""Partner Referrals v2 (raw HTTP). Swap for APIMatic client when #168 merges."""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from app.escales.config import SANDBOX_BASE, load_platform_config, public_base_url
from app.escales.paypal_client import PayPalClient, PayPalError

log = logging.getLogger("escales.project_onboarding.referrals")


class PartnerReferralsPort(Protocol):
    def create_referral(
        self,
        *,
        email: str,
        tracking_id: str,
        preferred_language_code: str,
        return_url: str,
    ) -> dict: ...

    def get_referral(self, partner_referral_id: str) -> dict: ...

    def merchant_integrations(self, *, partner_id: str, tracking_id: str) -> dict: ...


class RawHttpPartnerReferralsClient:
    """Sandbox-only Partner Referrals via PayPal REST."""

    def __init__(self, client: Optional[PayPalClient] = None):
        self._client = client or PayPalClient(load_platform_config())

    def create_referral(
        self,
        *,
        email: str,
        tracking_id: str,
        preferred_language_code: str,
        return_url: str,
    ) -> dict:
        body = {
            "tracking_id": tracking_id[:127],
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
            "products": ["EXPRESS_CHECKOUT"],
            "legal_consent": {"granted": True, "type": "SHARE_DATA_CONSENT"},
            "partner_config_override": {
                "return_url": return_url,
                "show_add_credit_card": False,
            },
            "email": email,
            "preferred_language_code": preferred_language_code,
        }
        return self._client._req("POST", "/v2/customer/partner-referrals", body)

    def get_referral(self, partner_referral_id: str) -> dict:
        token = str(partner_referral_id or "").strip()
        if not token:
            raise PayPalError(400, "partner_referral_id required")
        return self._client._req("GET", f"/v2/customer/partner-referrals/{token}")

    def merchant_integrations_by_tracking(self, *, partner_id: str, tracking_id: str) -> dict:
        """GET …/merchant-integrations?tracking_id= → merchant_id, tracking_id, links."""
        pid = str(partner_id or "").strip()
        if not pid:
            raise PayPalError(400, "partner_id required")
        from urllib.parse import quote

        tid = quote(str(tracking_id or ""), safe="")
        path = f"/v1/customer/partners/{pid}/merchant-integrations?tracking_id={tid}"
        return self._client._req("GET", path)

    def merchant_integrations(self, *, partner_id: str, tracking_id: str) -> dict:
        """Backward-compatible alias for tracking lookup."""
        return self.merchant_integrations_by_tracking(partner_id=partner_id, tracking_id=tracking_id)

    def merchant_integration_seller_status(self, *, partner_id: str, merchant_id: str) -> dict:
        """GET …/merchant-integrations/{merchant_id} → payments_receivable, primary_email_confirmed."""
        pid = str(partner_id or "").strip()
        mid = str(merchant_id or "").strip()
        if not pid or not mid:
            raise PayPalError(400, "partner_id and merchant_id required")
        from urllib.parse import quote

        path = f"/v1/customer/partners/{pid}/merchant-integrations/{quote(mid, safe='')}"
        return self._client._req("GET", path)


def action_url_from_referral(payload: dict) -> str:
    for link in payload.get("links") or []:
        if str(link.get("rel") or "").lower() == "action_url" and link.get("href"):
            return str(link["href"])
    for link in payload.get("links") or []:
        rel = str(link.get("rel") or "").lower()
        href = link.get("href") or ""
        if rel in {"self", "approve"} and href:
            continue
        if href and "referral" in rel:
            return str(href)
    return ""


def referral_self_href(payload: dict) -> tuple[str, str]:
    referral_id = str(payload.get("partner_referral_id") or payload.get("id") or "")
    for link in payload.get("links") or []:
        if str(link.get("rel") or "").lower() == "self" and link.get("href"):
            href = str(link["href"])
            if not referral_id and "/partner-referrals/" in href:
                referral_id = href.rstrip("/").split("/")[-1]
            return referral_id, href
    return referral_id, ""


def onboarding_return_url(project_id: str) -> str:
    base = public_base_url().rstrip("/")
    return f"{base}/projects/{project_id}/onboarding/return"


def assert_sandbox_base(client: PayPalClient) -> None:
    if client.cfg.base_url.rstrip("/") != SANDBOX_BASE:
        raise RuntimeError("Partner referrals require PayPal sandbox base URL")
