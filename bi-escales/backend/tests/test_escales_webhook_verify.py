"""Real verify-webhook-signature request shape, and the live call when credentials exist."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig, load_config
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.webhooks import signature_client

RAW = b'{"id":"WH-1","event_type":"PAYMENT.CAPTURE.REFUNDED","resource":{"id":"CAP-1"}}'


def _client(handler) -> PayPalClient:
    transport = httpx.MockTransport(handler)
    cfg = EscalesConfig(client_id="id", client_secret="secret")
    return PayPalClient(cfg, transport=transport)


def test_verify_posts_the_original_bytes_to_paypal():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 300})
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    client = _client(handler)
    result = client.verify_webhook_signature(
        auth_algo="SHA256withRSA",
        cert_url="https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        transmission_id="T-1",
        transmission_sig="sig",
        transmission_time="2026-11-04T00:00:00Z",
        webhook_id="WH-ID",
        webhook_event=json.loads(RAW),
        raw_event=RAW,
    )
    assert result["verification_status"] == "SUCCESS"
    assert seen["path"] == "/v1/notifications/verify-webhook-signature"
    assert RAW.decode() in seen["body"].decode()
    assert b"webhook_event" in seen["body"]


def test_signature_client_keeps_a_test_mock():
    class Stub:
        webhook_signature_mock = True

    stub = Stub()
    assert signature_client(stub) is stub


def test_signature_client_uses_paypal_client_when_credentials_are_set(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "live-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "live-secret")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-LIVE")

    class OrdersOnly:
        pass

    chosen = signature_client(OrdersOnly())
    assert isinstance(chosen, PayPalClient)
    assert chosen.cfg.client_id == "live-id"
    assert load_config().configured


@pytest.mark.live
def test_live_webhook_verify_reaches_sandbox():
    """Calls PayPal for real. Skipped until sandbox credentials are present.

    A forged body cannot verify. FAILURE (or any verification_status) means
    the live verify-webhook-signature endpoint answered.
    """
    if not os.environ.get("PAYPAL_CLIENT_ID") or not os.environ.get("PAYPAL_CLIENT_SECRET"):
        pytest.skip("PayPal sandbox credentials are not set")
    if not os.environ.get("PAYPAL_WEBHOOK_ID"):
        pytest.skip("PAYPAL_WEBHOOK_ID is not set")
    client = PayPalClient(load_config())
    try:
        result = client.verify_webhook_signature(
            auth_algo="SHA256withRSA",
            cert_url="https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
            transmission_id="T-LIVE-PROBE",
            transmission_sig="not-a-real-signature",
            transmission_time="2026-11-04T00:00:00Z",
            webhook_id=os.environ["PAYPAL_WEBHOOK_ID"],
            webhook_event=json.loads(RAW),
            raw_event=RAW,
        )
    except PayPalError as exc:
        assert exc.status < 500
        return
    status = str(result.get("verification_status") or "").upper()
    assert status in {"SUCCESS", "FAILURE"}
