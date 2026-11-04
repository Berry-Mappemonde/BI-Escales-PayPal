"""PayPal REST client (sandbox): OAuth, Orders v2 AUTHORIZE, capture, void, reads.

Orders v2: https://developer.paypal.com/docs/api/orders/v2/
Authorize then capture: https://developer.paypal.com/docs/checkout/standard/customize/authorization/
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import httpx

from .config import EscalesConfig


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal HTTP {status}")
        self.status = status
        self.body = body


def approve_link(order: dict) -> str:
    """Buyer approval URL from the order, or the sandbox checkout URL for its id."""
    for link in order.get("links") or []:
        rel = (link.get("rel") or "").lower()
        href = link.get("href") or ""
        if rel in {"approve", "payer-action"} and href:
            return href
    order_id = order.get("id") or ""
    return f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"


def authorization_from(order: dict) -> tuple[str, Optional[str]]:
    """Return (authorization id, expiration) from an authorize-order response."""
    for unit in order.get("purchase_units") or []:
        payments = unit.get("payments") or {}
        for auth in payments.get("authorizations") or []:
            auth_id = auth.get("id")
            if auth_id:
                expiration = auth.get("expiration_time")
                return str(auth_id), str(expiration) if expiration else None
    raise PayPalError(502, "authorization id missing")


class PayPalClient:
    def __init__(self, cfg: EscalesConfig, transport: Optional[httpx.BaseTransport] = None):
        self.cfg = cfg
        self._http = httpx.Client(base_url=cfg.base_url, transport=transport, timeout=30)
        self._token: Optional[str] = None
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        response = self._http.post(
            "/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.cfg.client_id, self.cfg.client_secret),
        )
        if response.status_code != 200:
            raise PayPalError(response.status_code, response.text)
        payload = response.json()
        self._token = payload["access_token"]
        self._token_exp = time.time() + int(payload.get("expires_in", 300))
        return self._token

    def _req(self, method: str, path: str, json: Any = None, idempotency_key: Optional[str] = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }
        if method in ("POST", "PATCH"):
            headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
        response = self._http.request(method, path, json=json, headers=headers)
        if response.status_code >= 400:
            raise PayPalError(response.status_code, response.text)
        return response.json() if response.content else {}

    def create_authorize_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [{
                "reference_id": reference_id[:256],
                "description": description[:127],
                "amount": {"currency_code": self.cfg.currency, "value": amount_eur},
            }],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key or f"order-{reference_id}",
        )

    def authorize_order(self, order_id: str) -> dict:
        return self._req(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            {},
            idempotency_key=f"authorize-{order_id}",
        )

    def capture_authorization(self, authorization_id: str, final: bool = True) -> dict:
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            {"final_capture": final},
            idempotency_key=f"cap-{authorization_id}",
        )

    def void_authorization(self, authorization_id: str) -> dict:
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            None,
            idempotency_key=f"void-{authorization_id}",
        )

    def reauthorize(self, authorization_id: str) -> dict:
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/reauthorize",
            {},
            idempotency_key=f"reauth-{authorization_id}",
        )

    def get_order(self, order_id: str) -> dict:
        return self._req("GET", f"/v2/checkout/orders/{order_id}")

    def get_authorization(self, authorization_id: str) -> dict:
        return self._req("GET", f"/v2/payments/authorizations/{authorization_id}")

    def create_setup_token(self, return_url: str, cancel_url: str) -> dict:
        body = {"payment_source": {"paypal": {
            "usage_type": "MERCHANT",
            "experience_context": {"return_url": return_url, "cancel_url": cancel_url},
        }}}
        return self._req("POST", "/v3/vault/setup-tokens", body)

    def create_payment_token(self, setup_token_id: str) -> dict:
        body = {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}}
        return self._req("POST", "/v3/vault/payment-tokens", body)

    def charge_vaulted(self, vault_id: str, amount_eur: str, reference_id: str) -> dict:
        body = {
            "intent": "CAPTURE",
            "payment_source": {"paypal": {"vault_id": vault_id}},
            "purchase_units": [{
                "reference_id": reference_id,
                "amount": {"currency_code": self.cfg.currency, "value": amount_eur},
            }],
        }
        return self._req("POST", "/v2/checkout/orders", body, idempotency_key=f"vault-{reference_id}")

    def delete_payment_token(self, vault_id: str) -> dict:
        return self._req("DELETE", f"/v3/vault/payment-tokens/{vault_id}")
