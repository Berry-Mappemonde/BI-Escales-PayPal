"""PayPal REST client (sandbox): OAuth, Orders v2 AUTHORIZE, capture, void, reads.

Orders v2: https://developer.paypal.com/docs/api/orders/v2/
Authorize then capture: https://developer.paypal.com/docs/checkout/standard/customize/authorization/
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

import httpx

from .config import EscalesConfig, order_cancel_url, order_return_url
from .paypal_idempotency import paypal_request_id

SOFT_DESCRIPTOR = "BERRYMAPPEMONDE"
VAULT_BRAND_NAME = "Berry-Mappemonde"
DEFAULT_PAYPAL_LOCALE = "fr-FR"


def paypal_checkout_locale(app_lang: Optional[str] = None) -> str:
    """Map app language (fr/en) to PayPal experience_context locale."""
    raw = (app_lang or "").strip().lower()
    if raw.startswith("en"):
        return "en-US"
    if raw.startswith("fr"):
        return "fr-FR"
    return DEFAULT_PAYPAL_LOCALE

log = logging.getLogger("escales.paypal")


def _paypal_api_error_fields(body: Any) -> Optional[dict[str, Any]]:
    parsed: Any = body
    if isinstance(body, str):
        text = body.strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    if not any(key in parsed for key in ("name", "debug_id", "details")):
        return None
    return {
        "name": parsed.get("name"),
        "debug_id": parsed.get("debug_id"),
        "details": parsed.get("details"),
    }


def paypal_public_error_detail(body: Any) -> Optional[str]:
    """JSON string with PayPal ``name``, ``debug_id``, and ``details`` when present."""
    fields = _paypal_api_error_fields(body)
    if not fields:
        return None
    return json.dumps(fields, default=str)


def _log_paypal_api_error(status: int, body: Any) -> None:
    fields = _paypal_api_error_fields(body)
    if not fields:
        return
    log.error(
        "PayPal HTTP %s name=%s debug_id=%s details=%s",
        status,
        fields.get("name"),
        fields.get("debug_id"),
        fields.get("details"),
    )


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal HTTP {status}")
        self.status = status
        self.body = body
        if status >= 400:
            _log_paypal_api_error(status, body)


def read_capture_result(payload: dict) -> tuple[str, Optional[str], Optional[str]]:
    """Return ``(status, capture_id, order_id)`` from a capture or an order.

    A vault charge nests the capture under ``purchase_units``. Its status wins
    over the order status. A bare capture resource uses its own id.
    """
    if not isinstance(payload, dict):
        return "", None, None
    units = payload.get("purchase_units") or []
    for unit in units:
        payments = (unit or {}).get("payments") or {}
        for cap in payments.get("captures") or []:
            if not isinstance(cap, dict):
                continue
            status = str(cap.get("status") or "").upper()
            capture_id = cap.get("id")
            order_id = payload.get("id")
            return (
                status,
                str(capture_id) if capture_id else None,
                str(order_id) if order_id else None,
            )
    status = str(payload.get("status") or "").upper()
    if units or payload.get("intent"):
        order_id = payload.get("id")
        return status, None, (str(order_id) if order_id else None)
    capture_id = payload.get("id")
    return status, (str(capture_id) if capture_id else None), None


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


def vault_source_from_token(payload: dict) -> str:
    """``card`` or ``paypal`` from a payment-token response. Wallet is the default."""
    source = payload.get("payment_source") or {}
    card = source.get("card")
    if isinstance(card, dict) and card:
        return "card"
    return "paypal"


def vault_id_from_token(payload: dict) -> str:
    """Payment token id from ``POST /v3/vault/payment-tokens``."""
    token_id = payload.get("id")
    if token_id:
        return str(token_id)
    source = payload.get("payment_source") or {}
    paypal = source.get("paypal") or {}
    nested = paypal.get("vault_id") or paypal.get("id")
    if nested:
        return str(nested)
    raise PayPalError(502, "vault id missing")


def vault_id_from_order(order: dict) -> Optional[str]:
    """Vault payment-token id saved during an AUTHORIZE checkout (vault on purchase)."""
    if not isinstance(order, dict):
        return None

    def walk(node: Any) -> Optional[str]:
        if isinstance(node, dict):
            vault_id = node.get("vault_id")
            if isinstance(vault_id, str) and vault_id.strip():
                return vault_id.strip()
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(order)


def setup_token_approve_link(payload: dict) -> str:
    for link in payload.get("links") or []:
        rel = (link.get("rel") or "").lower()
        href = link.get("href") or ""
        if rel in {"approve", "payer-action", "approve-url"} and href:
            return href
    token_id = payload.get("id") or ""
    return f"https://www.sandbox.paypal.com/agreements/approve?approval_session_id={token_id}"


class PayPalClient:
    def __init__(self, cfg: EscalesConfig, transport: Optional[httpx.BaseTransport] = None):
        self.cfg = cfg
        self._http = httpx.Client(base_url=cfg.base_url, transport=transport, timeout=30)
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self.mock_response: Optional[str] = None

    def _experience_context(
        self,
        return_url: str,
        cancel_url: str,
        *,
        locale: Optional[str] = None,
    ) -> dict:
        """Checkout experience_context shared by orders and vault setup."""
        return {
            "brand_name": VAULT_BRAND_NAME,
            "locale": paypal_checkout_locale(locale),
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "CONTINUE",
            "shipping_preference": "NO_SHIPPING",
        }

    def _purchase_unit(
        self,
        reference_id: str,
        description: str,
        amount_eur: str,
        *,
        payee_merchant_id: Optional[str] = None,
        platform_fee_eur: Optional[str] = None,
        platform_merchant_id: Optional[str] = None,
    ) -> dict:
        ref = str(reference_id or "")[:256]
        unit: dict = {
            "reference_id": ref,
            "description": str(description or "")[:127],
            "custom_id": ref[:127],
            "invoice_id": ref[:127],
            "soft_descriptor": SOFT_DESCRIPTOR,
            "amount": {"currency_code": self.cfg.currency, "value": amount_eur},
        }
        if payee_merchant_id:
            unit["payee"] = {"merchant_id": payee_merchant_id}
        fee = (platform_fee_eur or "").strip()
        platform_id = (platform_merchant_id or "").strip()
        if fee and platform_id:
            unit["payment_instruction"] = {
                "disbursement_mode": "INSTANT",
                "platform_fees": [
                    {
                        "amount": {"currency_code": self.cfg.currency, "value": fee},
                        "payee": {"merchant_id": platform_id},
                    }
                ],
            }
        return unit

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

    def _req(
        self,
        method: str,
        path: str,
        json: Any = None,
        idempotency_key: Optional[str] = None,
        content: Optional[bytes] = None,
        *,
        paypal_idempotent: bool = True,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }
        if method in ("POST", "PATCH") and paypal_idempotent:
            headers["PayPal-Request-Id"] = (idempotency_key or str(uuid.uuid4()))[:127]
            # Sandbox create/authorize omit intent and purchase_units unless asked.
            headers["Prefer"] = "return=representation"
        if self.mock_response:
            headers["PayPal-Mock-Response"] = self.mock_response
        if content is None:
            response = self._http.request(method, path, json=json, headers=headers)
        else:
            response = self._http.request(method, path, content=content, headers=headers)
        if response.status_code >= 400:
            raise PayPalError(response.status_code, response.text)
        return response.json() if response.content else {}

    def create_capture_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        idempotency_key: Optional[str] = None,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        checkout_locale: Optional[str] = None,
    ) -> dict:
        """Classic CAPTURE order (immediate payment after buyer approval)."""
        back = (return_url or "").strip() or order_return_url()
        cancel = (cancel_url or "").strip() or order_cancel_url()
        body = {
            "intent": "CAPTURE",
            "payment_source": {
                "paypal": {
                    "experience_context": self._experience_context(
                        back, cancel, locale=checkout_locale,
                    ),
                },
            },
            "purchase_units": [self._purchase_unit(reference_id, description, amount_eur)],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key or paypal_request_id(reference_id, "capture-order"),
        )

    def create_authorize_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        idempotency_key: Optional[str] = None,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        checkout_locale: Optional[str] = None,
        payee_merchant_id: Optional[str] = None,
        platform_fee_eur: Optional[str] = None,
        platform_merchant_id: Optional[str] = None,
    ) -> dict:
        """Classic AUTHORIZE order. Return and cancel URLs match the vault order."""
        back = (return_url or "").strip() or order_return_url()
        cancel = (cancel_url or "").strip() or order_cancel_url()
        body = {
            "intent": "AUTHORIZE",
            "payment_source": {
                "paypal": {
                    "experience_context": self._experience_context(
                        back, cancel, locale=checkout_locale,
                    ),
                },
            },
            "purchase_units": [
                self._purchase_unit(
                    reference_id,
                    description,
                    amount_eur,
                    payee_merchant_id=payee_merchant_id,
                    platform_fee_eur=platform_fee_eur,
                    platform_merchant_id=platform_merchant_id,
                )
            ],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key or paypal_request_id(reference_id, "order"),
        )

    def create_authorize_vault_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: Optional[str] = None,
        checkout_locale: Optional[str] = None,
    ) -> dict:
        """Orders v2 AUTHORIZE with store_in_vault ON_SUCCESS (production vault path)."""
        body = {
            "intent": "AUTHORIZE",
            "payment_source": {
                "paypal": {
                    "attributes": {"vault": {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT"}},
                    "experience_context": self._experience_context(
                        return_url, cancel_url, locale=checkout_locale,
                    ),
                },
            },
            "purchase_units": [self._purchase_unit(reference_id, description, amount_eur)],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key or paypal_request_id(reference_id, "vault-order"),
        )

    def create_card_authorize_order(
        self,
        amount_eur: str,
        description: str,
        reference_id: str,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: Optional[str] = None,
        checkout_locale: Optional[str] = None,
    ) -> dict:
        """Advanced card checkout: AUTHORIZE with SCA_WHEN_REQUIRED (see REVIEW_E2E.md card confirm path)."""
        body = {
            "intent": "AUTHORIZE",
            "payment_source": {
                "card": {
                    "attributes": {"verification": {"method": "SCA_WHEN_REQUIRED"}},
                    "experience_context": self._experience_context(
                        return_url, cancel_url, locale=checkout_locale,
                    ),
                },
            },
            "purchase_units": [self._purchase_unit(reference_id, description, amount_eur)],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key or paypal_request_id(reference_id, "card-order"),
        )

    def authorize_order(self, order_id: str, *, pledge_id: Optional[str] = None) -> dict:
        ref = pledge_id or order_id
        return self._req(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            {},
            idempotency_key=paypal_request_id(ref, "authorize"),
        )

    def capture_order(self, order_id: str, *, idempotency_key: str) -> dict:
        return self._req(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            {},
            idempotency_key=idempotency_key,
        )

    def capture_authorization(
        self,
        authorization_id: str,
        final: bool = True,
        *,
        idempotency_key: str,
    ) -> dict:
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            {"final_capture": final},
            idempotency_key=idempotency_key,
        )

    def void_authorization(self, authorization_id: str, *, pledge_id: Optional[str] = None) -> dict:
        ref = pledge_id or authorization_id
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            None,
            idempotency_key=paypal_request_id(ref, "void"),
        )

    def reauthorize(self, authorization_id: str, *, pledge_id: Optional[str] = None) -> dict:
        ref = pledge_id or authorization_id
        return self._req(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/reauthorize",
            {},
            idempotency_key=paypal_request_id(ref, "reauthorize"),
        )

    def get_order(self, order_id: str) -> dict:
        return self._req("GET", f"/v2/checkout/orders/{order_id}")

    def get_authorization(self, authorization_id: str) -> dict:
        return self._req("GET", f"/v2/payments/authorizations/{authorization_id}")

    def get_setup_token(self, setup_token_id: str) -> dict:
        return self._req("GET", f"/v3/vault/setup-tokens/{setup_token_id}")

    def create_setup_token(
        self,
        return_url: str,
        cancel_url: str,
        *,
        customer_id: str,
        idempotency_key: Optional[str] = None,
        checkout_locale: Optional[str] = None,
    ) -> dict:
        body = {
            "customer": {"id": str(customer_id)[:127]},
            "payment_source": {
                "paypal": {
                    "usage_type": "MERCHANT",
                    "usage_pattern": "UNSCHEDULED_POSTPAID",
                    "permit_multiple_payment_tokens": False,
                    "experience_context": self._experience_context(
                        return_url, cancel_url, locale=checkout_locale,
                    ),
                },
            },
        }
        return self._req(
            "POST",
            "/v3/vault/setup-tokens",
            body,
            idempotency_key=idempotency_key or paypal_request_id(customer_id, "setup-token"),
        )

    def create_card_setup_token(
        self,
        return_url: str,
        cancel_url: str,
        *,
        customer_id: str,
        idempotency_key: Optional[str] = None,
        checkout_locale: Optional[str] = None,
    ) -> dict:
        """Vault setup token for a card (SCA_WHEN_REQUIRED), same pattern as wallet setup tokens."""
        body = {
            "customer": {"id": str(customer_id)[:127]},
            "payment_source": {
                "card": {
                    "usage_type": "MERCHANT",
                    "usage_pattern": "UNSCHEDULED_POSTPAID",
                    "permit_multiple_payment_tokens": False,
                    "attributes": {"verification": {"method": "SCA_WHEN_REQUIRED"}},
                    "experience_context": self._experience_context(
                        return_url, cancel_url, locale=checkout_locale,
                    ),
                },
            },
        }
        return self._req(
            "POST",
            "/v3/vault/setup-tokens",
            body,
            idempotency_key=idempotency_key or paypal_request_id(customer_id, "card-setup-token"),
        )

    def create_payment_token(self, setup_token_id: str, *, pledge_id: Optional[str] = None) -> dict:
        ref = pledge_id or setup_token_id
        body = {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}}
        return self._req(
            "POST",
            "/v3/vault/payment-tokens",
            body,
            idempotency_key=paypal_request_id(ref, "payment-token"),
        )

    def charge_vaulted(
        self,
        vault_id: str,
        amount_eur: str,
        reference_id: str,
        source: str = "paypal",
        *,
        description: str = "",
        idempotency_key: str,
    ) -> dict:
        """Charge a saved payment token. ``source`` is ``paypal`` or ``card``."""
        kind = "card" if source == "card" else "paypal"
        source_body: dict = {"vault_id": vault_id}
        if kind == "card":
            source_body["stored_credential"] = {
                "payment_initiator": "MERCHANT",
                "payment_type": "UNSCHEDULED",
                "usage": "SUBSEQUENT",
            }
            source_body["attributes"] = {"verification": {"method": "SCA_WHEN_REQUIRED"}}
        body = {
            "intent": "CAPTURE",
            "payment_source": {kind: source_body},
            "purchase_units": [self._purchase_unit(reference_id, description or "Escales pledge", amount_eur)],
        }
        return self._req(
            "POST",
            "/v2/checkout/orders",
            body,
            idempotency_key=idempotency_key,
        )

    def list_disputes(self, *, start_time: Optional[str] = None) -> dict:
        path = "/v1/customer/disputes"
        if start_time:
            path = f"{path}?start_time={start_time}"
        return self._req("GET", path)

    def get_dispute(self, dispute_id: str) -> dict:
        return self._req("GET", f"/v1/customer/disputes/{dispute_id}")

    def accept_dispute_claim(self, dispute_id: str, *, note: str = "") -> dict:
        body = {"note": (note or "")[:512]} if note else {}
        return self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/accept-claim",
            body or None,
            idempotency_key=paypal_request_id(dispute_id, "accept-claim"),
        )

    def provide_dispute_evidence(
        self,
        dispute_id: str,
        *,
        notes: str,
        evidence_type: str = "PROOF_OF_FULFILLMENT",
    ) -> dict:
        body = {
            "evidence_type": evidence_type,
            "evidence_info": {"notes": (notes or "")[:2000]},
        }
        return self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/provide-evidence",
            body,
            idempotency_key=paypal_request_id(dispute_id, "provide-evidence"),
        )

    def create_invoice(
        self,
        *,
        recipient_email: str,
        amount_eur: str,
        description: str,
        reference: str,
        invoice_number: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> dict:
        number = (invoice_number or reference)[:25]
        body = {
            "detail": {
                "invoice_number": number,
                "currency_code": self.cfg.currency,
                "note": description[:2000],
                "payment_term": {"term_type": "NET_10"},
            },
            "primary_recipients": [{
                "billing_info": {"email_address": recipient_email},
            }],
            "items": [{
                "name": description[:100],
                "quantity": "1",
                "unit_amount": {"currency_code": self.cfg.currency, "value": amount_eur},
            }],
        }
        return self._req(
            "POST",
            "/v2/invoicing/invoices",
            body,
            idempotency_key=paypal_request_id(reference, "invoice-create"),
        )

    def send_invoice(self, invoice_id: str) -> dict:
        return self._req(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            {"send_to_recipient": True, "send_to_invoicer": False},
            idempotency_key=paypal_request_id(invoice_id, "invoice-send"),
        )

    def remind_invoice(
        self,
        invoice_id: str,
        *,
        subject: str,
        note: str,
    ) -> dict:
        return self._req(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/remind",
            {"subject": subject[:127], "note": note[:2000]},
            idempotency_key=paypal_request_id(invoice_id, "invoice-remind"),
        )

    def cancel_invoice(self, invoice_id: str) -> dict:
        return self._req(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/cancel",
            {"send_to_recipient": False, "send_to_invoicer": True},
            idempotency_key=paypal_request_id(invoice_id, "invoice-cancel"),
        )

    def delete_invoice(self, invoice_id: str) -> dict:
        return self._req("DELETE", f"/v2/invoicing/invoices/{invoice_id}")

    def get_invoice(self, invoice_id: str) -> dict:
        return self._req("GET", f"/v2/invoicing/invoices/{invoice_id}")

    def create_billing_product(
        self,
        *,
        name: str,
        description: str,
        idempotency_key: str,
    ) -> dict:
        body = {
            "name": name[:127],
            "description": description[:256],
            "type": "SERVICE",
            "category": "CHARITY",
        }
        return self._req("POST", "/v1/catalogs/products", body, idempotency_key=idempotency_key)

    def list_billing_products(self, *, page: int = 1, page_size: int = 20) -> dict:
        page_num = max(1, int(page))
        size = max(1, min(int(page_size), 100))
        return self._req(
            "GET",
            f"/v1/catalogs/products?page={page_num}&page_size={size}&total_required=true",
        )

    def iter_billing_product_pages(self, *, page_size: int = 20, max_pages: int = 50):
        """Yield each product list page until PayPal reports no further pages."""
        size = max(1, min(int(page_size), 100))
        cap = max(1, int(max_pages))
        for page in range(1, cap + 1):
            payload = self.list_billing_products(page=page, page_size=size)
            yield payload
            total_pages = int(payload.get("total_pages") or 1)
            if page >= total_pages:
                break

    def list_billing_plans(self, *, product_id: str, page_size: int = 20) -> dict:
        pid = str(product_id or "").strip()
        return self._req(
            "GET",
            f"/v1/billing/plans?product_id={pid}&page_size={page_size}&total_required=true",
        )

    def create_billing_plan(
        self,
        *,
        product_id: str,
        name: str,
        amount_eur: str,
        interval_unit: str,
        idempotency_key: str,
    ) -> dict:
        body = {
            "product_id": product_id,
            "name": name[:127],
            "billing_cycles": [{
                "frequency": {"interval_unit": interval_unit, "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {
                    "fixed_price": {"value": amount_eur, "currency_code": self.cfg.currency},
                },
            }],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
        }
        return self._req("POST", "/v1/billing/plans", body, idempotency_key=idempotency_key)

    def get_subscription(self, subscription_id: str) -> dict:
        return self._req("GET", f"/v1/billing/subscriptions/{subscription_id}")

    def create_billing_subscription(
        self,
        *,
        plan_id: str,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
        locale: Optional[str] = None,
    ) -> dict:
        checkout_locale = locale or DEFAULT_PAYPAL_LOCALE
        body = {
            "plan_id": plan_id,
            "application_context": {
                "brand_name": VAULT_BRAND_NAME,
                "locale": checkout_locale,
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        return self._req(
            "POST",
            "/v1/billing/subscriptions",
            body,
            idempotency_key=idempotency_key,
        )

    def refund_capture(
        self,
        capture_id: str,
        *,
        amount_eur: Optional[str] = None,
        idempotency_key: str,
    ) -> dict:
        """Refund a captured payment (full or partial).

        Captures API: https://developer.paypal.com/docs/api/payments/v2/#captures_refund
        """
        body: dict = {}
        if amount_eur:
            body["amount"] = {"currency_code": self.cfg.currency, "value": amount_eur}
        return self._req(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            body or None,
            idempotency_key=idempotency_key,
        )

    def create_payout(
        self,
        *,
        batch_id: str,
        receiver_email: str,
        amount_eur: str,
        note: str,
        item_id: str,
        lang: Optional[str] = None,
    ) -> dict:
        """Send one sandbox payout after explicit human approval.

        Payouts API: https://developer.paypal.com/docs/api/payments.payouts-batch/v1/
        """
        app_lang = (lang or "fr").strip().lower()
        if app_lang.startswith("en"):
            email_subject = "Berry-Mappemonde project payout"
            default_note = "Berry-Mappemonde Escales project payout"
        else:
            email_subject = "Versement projet Berry-Mappemonde"
            default_note = "Versement projet Escales Berry-Mappemonde"
        payout_note = (note or "").strip() or default_note
        body = {
            "sender_batch_header": {
                "sender_batch_id": batch_id[:127],
                "email_subject": email_subject,
            },
            "items": [{
                "recipient_type": "EMAIL",
                "recipient_wallet": "PAYPAL",
                "amount": {"value": str(amount_eur), "currency": self.cfg.currency or "EUR"},
                "receiver": receiver_email,
                "note": payout_note[:165],
                "sender_item_id": item_id[:127],
            }],
        }
        return self._req(
            "POST",
            "/v1/payments/payouts",
            body,
            idempotency_key=batch_id[:127],
        )

    def search_transactions(self, *, start_date: str, end_date: str) -> dict:
        from urllib.parse import urlencode

        from .paypal_txn_search import clamp_transaction_search_range

        start_date, end_date = clamp_transaction_search_range(start_date, end_date)
        query = urlencode({
            "start_date": start_date,
            "end_date": end_date,
            "fields": "all",
            "page_size": "100",
        })
        return self._req("GET", f"/v1/reporting/transactions?{query}")

    def list_invoices(self, *, page: int = 1, page_size: int = 20) -> dict:
        return self._req("GET", f"/v2/invoicing/invoices?page={page}&page_size={page_size}&total_required=true")

    def delete_payment_token(self, vault_id: str) -> dict:
        return self._req("DELETE", f"/v3/vault/payment-tokens/{vault_id}")

    def verify_webhook_signature(
        self,
        *,
        auth_algo: str,
        cert_url: str,
        transmission_id: str,
        transmission_sig: str,
        transmission_time: str,
        webhook_id: str,
        webhook_event: dict,
        raw_event: Optional[bytes] = None,
    ) -> dict:
        """Verify a webhook. ``raw_event`` is spliced in unchanged.

        Re-serializing the event can change spacing, and PayPal then rejects
        a signature that was computed on the original body.
        """
        import json as _json

        meta = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": webhook_id,
        }
        if raw_event is None:
            meta["webhook_event"] = webhook_event
            return self._req("POST", "/v1/notifications/verify-webhook-signature", meta)
        if raw_event.startswith(b"\xef\xbb\xbf"):
            raw_event = raw_event[3:]
        encoded = raw_event.decode("utf-8")
        _json.loads(encoded)
        prefix = _json.dumps(meta, separators=(",", ":"), ensure_ascii=False)
        body = prefix[:-1] + ',"webhook_event":' + encoded + "}"
        return self._req(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            content=body.encode("utf-8"),
            paypal_idempotent=False,
        )
