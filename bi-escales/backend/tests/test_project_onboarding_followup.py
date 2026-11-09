"""PROJ-ONBOARD-FOLLOWUP: webhook verify kwargs and guarded donation capture."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig, SANDBOX_BASE
from app.escales.paypal_client import PayPalClient
from app.escales import rate_limit as rate_limit_module
from app.project_onboarding.constants import DEMO_PROJECT_ID
from app.project_onboarding.store import reset_onboarding_store
from app.routers import project_onboarding as onboarding_router
from tests.test_project_onboarding import MockPayPal

WEBHOOK_HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "tx-followup",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-09T00:00:00Z",
    "PAYPAL-TRANSMISSION-SIG": "c2ln",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
}


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


def _webhook_paypal_client(*, verification_status: str) -> PayPalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            assert b'"webhook_event":' in request.content
            return httpx.Response(200, json={"verification_status": verification_status})
        return httpx.Response(404, json={"name": "NOT_FOUND"})

    return PayPalClient(
        EscalesConfig(client_id="cid", client_secret="secret", base_url=SANDBOX_BASE, env="sandbox"),
        transport=httpx.MockTransport(handler),
    )


def test_merchant_webhook_verification_hits_paypal_http_layer(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    monkeypatch.setattr(
        "app.routers.project_onboarding._paypal_client",
        lambda: _webhook_paypal_client(verification_status="FAILURE"),
    )
    payload = {
        "id": "WH-HTTP-FAIL",
        "event_type": "MERCHANT.ONBOARDING.COMPLETED",
        "resource": {"tracking_id": DEMO_PROJECT_ID},
    }
    res = onboarding_api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=WEBHOOK_HEADERS,
        content=json.dumps(payload),
    )
    assert res.status_code == 401


def test_merchant_webhook_valid_signature_processed(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    monkeypatch.setattr(
        "app.routers.project_onboarding._paypal_client",
        lambda: _webhook_paypal_client(verification_status="SUCCESS"),
    )
    payload = {
        "id": "WH-HTTP-OK",
        "event_type": "MERCHANT.ONBOARDING.COMPLETED",
        "resource": {"tracking_id": DEMO_PROJECT_ID, "merchant_id": "MERCH-HTTP"},
    }
    res = onboarding_api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=WEBHOOK_HEADERS,
        content=json.dumps(payload),
    )
    assert res.status_code == 200
    assert res.json().get("accepted") is True


def test_capture_unknown_donation_skips_paypal_capture(onboarding_api, monkeypatch):
    mock = MockPayPal()
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    res = onboarding_api.post("/api/escales/project-onboarding/donations/missing-donation/capture")
    assert res.status_code == 404
    assert mock.capture_calls == []


def test_capture_not_approved_returns_409_without_capture(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal(order_status="CREATED")
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "10.00"},
    ).json()
    res = onboarding_api.post(f"/api/escales/project-onboarding/donations/{created['_id']}/capture")
    assert res.status_code == 409
    assert mock.capture_calls == []


class CaptureRouteHttpSpy:
    """PayPal client via MockTransport; records capture POSTs for route-level tests."""

    def __init__(self, *, order_body: dict):
        self.order_body = dict(order_body)
        self.capture_paths: list[str] = []
        self._client: PayPalClient | None = None

    def client(self) -> PayPalClient:
        if self._client is None:
            spy = self

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/v1/oauth2/token":
                    return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
                if request.method == "GET" and request.url.path.startswith("/v2/checkout/orders/"):
                    body = dict(spy.order_body)
                    body.setdefault("id", request.url.path.rsplit("/", 1)[-1])
                    body.setdefault("status", "APPROVED")
                    return httpx.Response(200, json=body)
                if request.method == "POST" and request.url.path.endswith("/capture"):
                    spy.capture_paths.append(request.url.path)
                    return httpx.Response(
                        201,
                        json={
                            "status": "COMPLETED",
                            "purchase_units": [
                                {"payments": {"captures": [{"id": "CAP-HTTP-SPY", "status": "COMPLETED"}]}}
                            ],
                        },
                    )
                if request.method == "POST" and request.url.path == "/v2/checkout/orders":
                    created = request.read()
                    import json as _json

                    _ = _json.loads(created) if created else {}
                    return httpx.Response(
                        201,
                        json={
                            "id": "ORDER-MOCK",
                            "links": [
                                {
                                    "rel": "approve",
                                    "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-MOCK",
                                }
                            ],
                        },
                    )
                return httpx.Response(404, json={"name": "NOT_FOUND"})

            self._client = PayPalClient(
                EscalesConfig(client_id="cid", client_secret="secret", base_url=SANDBOX_BASE, env="sandbox"),
                transport=httpx.MockTransport(handler),
            )
        return self._client


def test_capture_rejects_foreign_order_metadata_without_paypal_capture(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    spy = CaptureRouteHttpSpy(
        order_body={
            "id": "ORDER-MOCK",
            "status": "APPROVED",
            "purchase_units": [
                {
                    "reference_id": "donation-belongs-to-another-row",
                    "custom_id": DEMO_PROJECT_ID,
                }
            ],
        }
    )
    monkeypatch.setattr("app.project_onboarding.service._paypal", spy.client)
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "12.00"},
    ).json()
    assert created.get("order_id") == "ORDER-MOCK"
    res = onboarding_api.post(
        f"/api/escales/project-onboarding/donations/{created['_id']}/capture",
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "PayPal order does not match this donation"
    assert spy.capture_paths == []


def test_capture_matching_order_metadata_calls_paypal_capture_once(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: CaptureRouteHttpSpy(order_body={}).client())
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "11.00"},
    ).json()
    spy = CaptureRouteHttpSpy(
        order_body={
            "id": created["order_id"],
            "status": "APPROVED",
            "purchase_units": [
                {
                    "reference_id": created["_id"],
                    "custom_id": DEMO_PROJECT_ID,
                }
            ],
        }
    )
    monkeypatch.setattr("app.project_onboarding.service._paypal", spy.client)
    res = onboarding_api.post(
        f"/api/escales/project-onboarding/donations/{created['_id']}/capture",
    )
    assert res.status_code == 200
    assert res.json().get("capture_id") == "CAP-HTTP-SPY"
    assert len(spy.capture_paths) == 1
    assert spy.capture_paths[0].endswith(f"/v2/checkout/orders/{created['order_id']}/capture")


def test_capture_rate_limit_returns_429(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal()
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "2")
    rate_limit_module.reset()
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "10.00"},
    ).json()
    path = f"/api/escales/project-onboarding/donations/{created['_id']}/capture"
    assert onboarding_api.post(path).status_code == 200
    assert onboarding_api.post(path).status_code == 200
    blocked = onboarding_api.post(path)
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")
