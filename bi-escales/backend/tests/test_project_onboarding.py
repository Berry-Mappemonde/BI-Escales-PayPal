"""Onboard-after-payment C2–C8 (PayPal + email mocked)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.project_onboarding.constants import (
    DEMO_PROJECT_ID,
    ONBOARDED_STATUS,
    ONBOARDING_HELD_STATUS,
    ONBOARDING_REQUIRED_STATUS,
)
from app.project_onboarding.store import reset_onboarding_store
from app.escales.config import EscalesConfig, SANDBOX_BASE
from app.routers import project_onboarding as onboarding_router


class MockPayPal:
    def __init__(
        self,
        *,
        capture_status: int = 201,
        capture_body: dict | None = None,
        fail_capture: bool = False,
        fail_referral_status: int = 0,
        seller_receivable: bool = True,
        seller_email_confirmed: bool = True,
        order_status: str = "APPROVED",
    ):
        self.cfg = EscalesConfig(client_id="cid", client_secret="secret", base_url=SANDBOX_BASE, env="sandbox")
        self.order_status = order_status
        self.capture_calls: list[str] = []
        self.capture_status = capture_status
        self.capture_body = capture_body or {
            "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [{"id": "CAP-MOCK", "status": "COMPLETED"}]}}],
        }
        self.fail_capture = fail_capture
        self.fail_referral_status = fail_referral_status
        self.seller_receivable = seller_receivable
        self.seller_email_confirmed = seller_email_confirmed
        self.orders: list[dict] = []
        self.referrals: list[dict] = []

    def _access_token(self):
        return "mock-token"

    def _request_with_retry(self, method, path, **kwargs):
        import httpx

        if method == "POST" and path == "/v2/checkout/orders":
            body = kwargs.get("json") or {}
            self.orders.append(body)
            response = httpx.Response(
                201,
                json={
                    "id": "ORDER-MOCK",
                    "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-MOCK"}],
                },
            )
            return response
        if method == "GET" and "/v2/checkout/orders/" in path and not path.endswith("/capture"):
            order_id = path.rsplit("/", 1)[-1]
            unit = {}
            if self.orders:
                unit = dict((self.orders[-1].get("purchase_units") or [{}])[0])
            return httpx.Response(
                200,
                json={
                    "id": order_id,
                    "status": self.order_status,
                    "purchase_units": [unit] if unit else [],
                },
            )
        if method == "POST" and path.endswith("/capture"):
            prefix = "/v2/checkout/orders/"
            order_id = path[len(prefix) :].split("/capture", 1)[0] if prefix in path else path
            self.capture_calls.append(order_id)
            if self.fail_capture:
                response = httpx.Response(500, text='{"name":"UNPROCESSABLE_ENTITY"}')
                return response
            return httpx.Response(self.capture_status, json=self.capture_body)
        if method == "POST" and path == "/v2/customer/partner-referrals":
            if self.fail_referral_status:
                return httpx.Response(self.fail_referral_status, text='{"name":"NOT_AUTHORIZED"}')
            self.referrals.append(kwargs.get("json"))
            return httpx.Response(
                201,
                json={
                    "partner_referral_id": "REF-MOCK",
                    "links": [
                        {"rel": "action_url", "href": "https://www.sandbox.paypal.com/merchantsignup?token=REF"},
                        {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-MOCK"},
                    ],
                },
            )
        if method == "GET" and "/partner-referrals/" in path:
            return httpx.Response(
                200,
                json={
                    "partner_referral_id": "REF-MOCK",
                    "links": [{"rel": "action_url", "href": "https://www.sandbox.paypal.com/merchantsignup?token=REF"}],
                },
            )
        if "merchant-integrations" in path:
            if "tracking_id=" in path:
                return httpx.Response(
                    200,
                    json={
                        "merchant_id": "MERCH-MOCK",
                        "tracking_id": DEMO_PROJECT_ID,
                        "links": [],
                    },
                )
            if "/merchant-integrations/" in path:
                return httpx.Response(
                    200,
                    json={
                        "merchant_id": "MERCH-MOCK",
                        "payments_receivable": self.seller_receivable,
                        "primary_email_confirmed": self.seller_email_confirmed,
                    },
                )
        raise AssertionError(f"unexpected {method} {path}")

    def get_order(self, order_id: str):
        response = self._request_with_retry("GET", f"/v2/checkout/orders/{order_id}")
        return response.json()

    def _req(self, method, path, json=None, idempotency_key=None, content=None, **kwargs):
        response = self._request_with_retry(method, path, json=json)
        from app.escales.paypal_client import PayPalError

        if response.status_code >= 400:
            raise PayPalError(response.status_code, response.text)
        return response.json()

    def _experience_context(self, back, cancel, locale=None):
        return {"return_url": back, "cancel_url": cancel, "locale": locale or "fr-FR"}

    def verify_webhook_signature(self, **kwargs):
        return {"verification_status": "SUCCESS"}


@pytest.fixture
def onboarding_api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_DEMO_PROJECT_CONTACT_EMAIL", "project@example.com")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "wh-mock")
    reset_onboarding_store()
    app = FastAPI()
    app.include_router(onboarding_router.router)
    app.include_router(onboarding_router.webhooks_router)
    with TestClient(app) as client:
        yield client
    reset_onboarding_store()


def test_seed_idempotent_berry_project(onboarding_api):
    first = onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    second = onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    assert first.status_code == 200
    assert second.status_code == 200
    project = first.json()["project"]
    assert project["_id"] == DEMO_PROJECT_ID
    assert "Berry-Mappemonde" in project["title_en"]
    assert project.get("demo_fake") is not True
    assert project.get("image_url") == "/static/onboarding/berry-mappemonde-logo.webp"
    assert project.get("location_label") == "Saint-Maur (Indre), France"
    assert "36 mois" in project["description_fr"]
    assert "exposition itinérante" in project["description_fr"]
    assert "36-month" in project["description_en"]
    assert "travelling exhibition" in project["description_en"]
    assert second.json()["project"]["onboarding_status"] == first.json()["project"]["onboarding_status"]


def test_donation_order_uses_payee_and_custom_id(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal()
    monkeypatch.setattr(
        "app.project_onboarding.service._paypal",
        lambda: mock,
    )
    res = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "25.00", "contributor": "Donor"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["order_id"] == "ORDER-MOCK"
    assert mock.orders
    unit = mock.orders[0]["purchase_units"][0]
    assert unit["custom_id"] == DEMO_PROJECT_ID
    assert unit["payee"]["email_address"] == "project@example.com"


def test_capture_held_pending_deadline(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal()
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "10.00"},
    ).json()
    cap = onboarding_api.post(f"/api/escales/project-onboarding/donations/{created['_id']}/capture")
    assert cap.status_code == 200
    row = cap.json()
    assert row["status"] == ONBOARDING_HELD_STATUS
    assert row["capture_id"] == "CAP-MOCK"
    assert row["deadline_at"]
    assert "2027" not in row["deadline_at"]


def test_capture_fallback_onboarding_required(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal(fail_capture=True)
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "12.00"},
    ).json()
    cap = onboarding_api.post(f"/api/escales/project-onboarding/donations/{created['_id']}/capture")
    assert cap.status_code == 200
    row = cap.json()
    assert row["status"] == ONBOARDING_REQUIRED_STATUS
    link = onboarding_api.post(f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/onboarding-link")
    assert link.status_code == 200
    assert link.json().get("action_url")


def test_email_preview_and_copy_link(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal()
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "5.00"},
    )
    preview = onboarding_api.get(f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/email/preview")
    assert preview.status_code == 200
    assert "sandbox" in preview.text.lower()
    copy = onboarding_api.get(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/onboarding-link/copy",
        headers={"x-admin-key": "test-admin"},
    )
    assert copy.status_code == 200
    assert copy.json()["action_url"]


def test_onboarding_return_marks_onboarded(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", "PARTNER-MOCK")
    mock = MockPayPal()
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    res = onboarding_api.get(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/onboarding/return",
        params={"merchantIdInPayPal": "MERCH-1", "permissionsGranted": "true", "isEmailConfirmed": "true"},
    )
    assert res.status_code == 200
    view = onboarding_api.get(f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}")
    assert view.json()["onboarding_status"] == ONBOARDED_STATUS


def test_merchant_webhook_idempotent(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal()
    monkeypatch.setattr("app.routers.project_onboarding._paypal_client", lambda: mock)
    payload = {
        "id": "WH-EVENT-1",
        "event_type": "MERCHANT.ONBOARDING.COMPLETED",
        "resource": {"tracking_id": DEMO_PROJECT_ID, "merchant_id": "MERCH-2"},
    }
    headers = {
        "PAYPAL-TRANSMISSION-ID": "tx-1",
        "PAYPAL-TRANSMISSION-TIME": "2026-11-09T00:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2ln",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    }
    first = onboarding_api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=headers,
        content=json.dumps(payload),
    )
    second = onboarding_api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=headers,
        content=json.dumps(payload),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json().get("duplicate") is True


def test_feature_off_returns_404(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "0")
    app = FastAPI()
    app.include_router(onboarding_router.router)
    client = TestClient(app)
    assert client.get(f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}").status_code == 404
