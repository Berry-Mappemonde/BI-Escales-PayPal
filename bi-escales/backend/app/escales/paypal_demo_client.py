"""In-memory PayPal stand-in for local demo and Playwright (no network, no secrets)."""
from __future__ import annotations

from typing import Any, Optional


class DemoPayPalClient:
    """Combines AUTHORIZE, Vault v3, and webhook verification for visual review runs."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.n = 0

    def verify_webhook_signature(self, **kwargs: Any) -> dict:
        self.calls.append(("verify_webhook", kwargs.get("webhook_id")))
        return {"verification_status": "SUCCESS"}

    def create_authorize_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        self.calls.append(("create_authorize", amount_eur, idempotency_key))
        self.n += 1
        order_id = f"DEMO-ORDER-{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
            }],
        }

    def create_setup_token(self, return_url: str, cancel_url: str) -> dict:
        self.calls.append(("setup_token", return_url, cancel_url))
        self.n += 1
        token = f"DEMO-SETUP-{self.n}"
        return {
            "id": token,
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/agreements/approve?token={token}",
            }],
        }

    def get_setup_token(self, setup_token_id: str) -> dict:
        self.calls.append(("get_setup_token", setup_token_id))
        return {"id": setup_token_id, "status": "APPROVED"}

    def create_payment_token(self, setup_token_id: str) -> dict:
        self.calls.append(("payment_token", setup_token_id))
        return {"id": f"DEMO-VAULT-{setup_token_id}"}

    def charge_vaulted(self, vault_id: str, amount_eur: str, reference_id: str) -> dict:
        self.calls.append(("charge_vaulted", vault_id, amount_eur, reference_id))
        return {"id": f"CAP-V-{reference_id}", "status": "COMPLETED"}

    def delete_payment_token(self, vault_id: str) -> dict:
        self.calls.append(("delete_token", vault_id))
        return {}

    def authorize_order(self, order_id: str) -> dict:
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"DEMO-AUTH-{order_id}",
                        "expiration_time": "2026-12-01T00:00:00Z",
                    }],
                },
            }],
        }

    def capture_authorization(self, authorization_id: str, final: bool = True) -> dict:
        self.calls.append(("capture", authorization_id, final))
        return {"id": f"DEMO-CAP-{authorization_id}", "status": "COMPLETED"}

    def void_authorization(self, authorization_id: str) -> dict:
        self.calls.append(("void", authorization_id))
        return {}

    def reauthorize(self, authorization_id: str) -> dict:
        self.calls.append(("reauthorize", authorization_id))
        return {"id": f"DEMO-AUTH2-{authorization_id}"}

    def get_order(self, order_id: str) -> dict:
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id: str) -> dict:
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


_client: DemoPayPalClient | None = None


def demo_client_factory() -> DemoPayPalClient:
    """One client per process so order and authorization ids stay unique."""
    global _client
    if _client is None:
        _client = DemoPayPalClient()
    return _client


def reset_demo_client() -> None:
    global _client
    _client = None
