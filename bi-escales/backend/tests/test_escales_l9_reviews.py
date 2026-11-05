"""L9 review fixes: capture status, honor period, CORS, flags, mongo handle."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm import llm_enabled, nebius_enabled
from app.escales.config import (
    marina_payouts_enabled,
    platform_fees_enabled,
    EscalesConfig,
    bryntum_scheduler_enabled,
    card_fields_enabled,
    channel3_enabled,
    elastic_evidence_enabled,
    escales_enabled,
    kernel_evidence_enabled,
    limits_enabled,
    naviguide_bridge_enabled,
    toolkit_enabled,
    vault_enabled,
    vault_on_purchase_enabled,
    wallet_pay_enabled,
    webhooks_enabled,
    zapiper_enabled,
)
from app.escales.ledger import MongoLedger, get_ledger, reset_ledger
from app.escales.paypal_client import PayPalClient, read_capture_result
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge
from app.main import install_cors
from app.routers.escales import router, set_paypal_client_factory
from tests.near_horizon import seed_near

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

FLAG_GETTERS = {
    "ESCALES_ENABLED": escales_enabled,
    "ESCALES_TOOLKIT_ENABLED": toolkit_enabled,
    "ESCALES_NAVIGUIDE_ENABLED": naviguide_bridge_enabled,
    "ESCALES_ELASTIC_ENABLED": elastic_evidence_enabled,
    "ESCALES_KERNEL_ENABLED": kernel_evidence_enabled,
    "ESCALES_CHANNEL3_ENABLED": channel3_enabled,
    "ESCALES_BRYNTUM_ENABLED": bryntum_scheduler_enabled,
    "ESCALES_VAULT_ENABLED": vault_enabled,
    "ESCALES_CARD_FIELDS_ENABLED": card_fields_enabled,
    "ESCALES_VAULT_ON_PURCHASE_ENABLED": vault_on_purchase_enabled,
    "ESCALES_WALLET_PAY_ENABLED": wallet_pay_enabled,
    "ESCALES_WEBHOOKS_ENABLED": webhooks_enabled,
    "ESCALES_ZAPIER_ENABLED": zapiper_enabled,
    "ESCALES_LLM_ENABLED": llm_enabled,
    "ESCALES_LLM_NEBIUS_ENABLED": nebius_enabled,
    "ESCALES_RATE_LIMIT_ENABLED": limits_enabled,
    "ESCALES_MARINA_PAYOUTS_ENABLED": marina_payouts_enabled,
    "ESCALES_PLATFORM_FEES_ENABLED": platform_fees_enabled,
}


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T12:00:00Z")
    monkeypatch.delenv("ESCALES_VAULT_ENABLED", raising=False)
    reset_ledger()
    asyncio.run(seed_near())
    yield
    reset_ledger()


class CaptureSpy:
    def __init__(self, capture_body):
        self.capture_body = capture_body
        self.calls = []
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.n += 1
        return {"id": f"ORDER{self.n}", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORDER"}]}

    def authorize_order(self, order_id, **kwargs):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2027-12-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, authorization_id, final=True, idempotency_key=None):
        self.calls.append(("capture", authorization_id))
        return self.capture_body

    def reauthorize(self, authorization_id, **kwargs):
        self.calls.append(("reauthorize", authorization_id))
        return {"id": "AUTH-RE", "expiration_time": "2027-07-01T00:00:00Z"}


def test_capture_pending_is_recorded_as_pending(memory):
    async def body():
        spy = CaptureSpy({"id": "CAP-P", "status": "PENDING"})
        created = await create_pledge(
            amount_eur="20.00", description="20 milles", milestone_id="dep-mayotte", client=spy, client_key="pend",
        )
        await authorize_pledge(created["_id"], spy)
        pending = await capture_pledge(created["_id"], spy)
        assert pending["status"] == "pending"
        assert pending["paypal_status"] == "PENDING"
        assert pending["capture_id"] == "CAP-P"
        assert ("reauthorize",) not in [(call[0],) for call in spy.calls]

    asyncio.run(body())


def test_declined_capture_stays_authorized_for_retry(memory):
    async def body():
        spy = CaptureSpy({"id": "CAP-D", "status": "DECLINED"})
        created = await create_pledge(
            amount_eur="20.00", description="20 milles", milestone_id="dep-mayotte", client=spy, client_key="dec",
        )
        await authorize_pledge(created["_id"], spy)
        with pytest.raises(ValueError, match="not COMPLETED or PENDING"):
            await capture_pledge(created["_id"], spy)
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored["status"] == "capture_failed"
        assert stored["paypal_status"] == "DECLINED"
        spy.capture_body = {"id": "CAP-OK", "status": "COMPLETED"}
        captured = await capture_pledge(created["_id"], spy)
        assert captured["status"] == "captured"
        assert captured["capture_id"] == "CAP-OK"
        assert captured["paypal_status"] == "COMPLETED"

    asyncio.run(body())


def test_honor_period_reauthorizes_then_captures(memory):
    async def body():
        spy = CaptureSpy({"id": "CAP-H", "status": "COMPLETED"})
        created = await create_pledge(
            amount_eur="20.00", description="20 milles", milestone_id="dep-mayotte", client=spy, client_key="hon",
        )
        authorized = await authorize_pledge(created["_id"], spy)
        authorized["authorized_at"] = "2020-01-01T00:00:00+00:00"
        await get_ledger().save_pledge(authorized)
        captured = await capture_pledge(created["_id"], spy)
        assert ("reauthorize", "AUTH-ORDER1") in [(call[0], call[1]) for call in spy.calls]
        assert captured["authorization_id"] == "AUTH-RE"
        assert captured["status"] == "captured"
        assert ("capture", "AUTH-RE") in [(call[0], call[1]) for call in spy.calls]

    asyncio.run(body())


def test_expired_authorization_is_not_captured(memory):
    async def body():
        spy = CaptureSpy({"id": "CAP-X", "status": "COMPLETED"})
        created = await create_pledge(
            amount_eur="20.00", description="20 milles", milestone_id="dep-mayotte", client=spy, client_key="exp",
        )
        authorized = await authorize_pledge(created["_id"], spy)
        authorized["authorization_expires_at"] = "2020-01-01T00:00:00+00:00"
        await get_ledger().save_pledge(authorized)
        with pytest.raises(ValueError, match="expired"):
            await capture_pledge(created["_id"], spy)
        assert all(call[0] != "capture" for call in spy.calls)
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored["status"] == "authorized"

    asyncio.run(body())


def test_read_capture_result_prefers_nested_capture_status():
    status, capture_id, order_id = read_capture_result({
        "id": "ORDER",
        "status": "COMPLETED",
        "intent": "CAPTURE",
        "purchase_units": [{"payments": {"captures": [{"id": "CAP", "status": "PENDING"}]}}],
    })
    assert (status, capture_id, order_id) == ("PENDING", "CAP", "ORDER")


def test_verify_webhook_keeps_the_raw_event_bytes():
    raw = b'{"id":"WH-1","resource":{"note":"keep  spaces"}}'
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        seen["body"] = request.content
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    client = PayPalClient(EscalesConfig("id", "secret"), transport=httpx.MockTransport(handler))
    client.verify_webhook_signature(
        auth_algo="SHA256withRSA",
        cert_url="https://example.test/cert",
        transmission_id="T",
        transmission_sig="sig",
        transmission_time="2026-11-04T00:00:00Z",
        webhook_id="WH",
        webhook_event={"id": "changed"},
        raw_event=raw,
    )
    assert b"keep  spaces" in seen["body"]
    assert b'"webhook_event":{"id":"WH-1"' in seen["body"]
    assert b'"id":"changed"' not in seen["body"]


def test_cors_reflects_only_configured_origins(monkeypatch):
    monkeypatch.setenv("ESCALES_CORS_ORIGINS", "https://front.example, http://localhost:5173")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    install_cors(app)
    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "https://front.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-admin-key,paypal-request-id",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://front.example"
        blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in blocked.headers

    monkeypatch.delenv("ESCALES_CORS_ORIGINS", raising=False)
    bare = FastAPI()

    @bare.get("/api/health")
    def health_bare():
        return {"status": "ok"}

    install_cors(bare)
    with TestClient(bare) as client:
        response = client.get("/api/health", headers={"Origin": "https://front.example"})
        assert "access-control-allow-origin" not in response.headers


def test_every_escales_enabled_flag_is_off_by_default(monkeypatch):
    found = set()
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r'"(ESCALES_[A-Z0-9_]*ENABLED)"', text))
        assert re.search(
            r'ESCALES_[A-Z0-9_]*ENABLED"\s*,\s*["\'](?:1|true|yes|on)',
            text,
            re.IGNORECASE,
        ) is None
    assert found == set(FLAG_GETTERS)
    for name, getter in FLAG_GETTERS.items():
        monkeypatch.delenv(name, raising=False)
        assert getter() is False, name
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in FLAG_GETTERS:
        if name == "ESCALES_ENABLED":
            continue
        assert any(line.strip() == f"{name}=" or line.strip().startswith(f"{name}=") for line in example.splitlines()), name
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "demo-admin-key" not in render
    assert "ESCALES_VAULT_ENABLED" in render
    assert 'value: "true"' in render
    assert "ESCALES_LLM_ENABLED" in render


def test_mongo_ledger_uses_app_db(monkeypatch):
    import app.db as dbmod

    monkeypatch.setenv("ESCALES_STORE", "mongo")
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    reset_ledger()
    dbmod.reset_db()
    columns = {}

    class _FakeDB:
        def __getitem__(self, name):
            columns.setdefault(name, object())
            return columns[name]

    class _FakeClient:
        def __getitem__(self, _name):
            return _FakeDB()

    monkeypatch.setattr(dbmod, "get_client", lambda: _FakeClient())
    try:
        ledger = get_ledger()
        assert isinstance(ledger, MongoLedger)
        assert "escales_pledges" in columns
        assert "escales_webhooks" in columns
        assert ledger._webhooks is columns["escales_webhooks"]
    finally:
        reset_ledger()
        dbmod.reset_db()


def test_db_requires_mongo_url(monkeypatch):
    import app.db as dbmod

    monkeypatch.delenv("MONGO_URL", raising=False)
    dbmod.reset_db()
    with pytest.raises(RuntimeError, match="MONGO_URL"):
        dbmod.get_db()


def test_admin_can_list_pledges_and_finance(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T12:00:00Z")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    asyncio.run(seed_near())

    class Spy(CaptureSpy):
        def __init__(self):
            super().__init__({"id": "CAP", "status": "COMPLETED"})

    fake = Spy()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/escales/pledges",
                json={"amount_eur": "20.00", "description": "20 milles", "milestone_id": "dep-mayotte"},
                headers={"PayPal-Request-Id": "admin-list"},
            )
            assert created.status_code == 200, created.text
            denied = client.get("/api/escales/pledges")
            assert denied.status_code == 401
            listed = client.get("/api/escales/pledges", headers={"x-admin-key": "test-admin-key"})
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == created.json()["id"]
    finally:
        set_paypal_client_factory(None)
        reset_ledger()
