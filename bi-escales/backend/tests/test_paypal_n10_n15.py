"""Crew supporter fixes N10–N15 (plan read route, URL allow-list, idempotency)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.paypal_subscriptions import ensure_crew_supporter_catalog
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory
from tests.test_paypal_n1_n5 import NSpy


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def test_n10_get_subscription_plan_is_read_only_and_does_not_create():
    async def run():
        spy = NSpy()
        set_paypal_client_factory(lambda: spy)
        await ensure_crew_supporter_catalog(spy)
        sub_create_count = 0
        original_create = spy.create_billing_subscription

        def counting_create(**kwargs):
            nonlocal sub_create_count
            sub_create_count += 1
            return original_create(**kwargs)

        spy.create_billing_subscription = counting_create
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        body = client.get("/api/escales/paypal/subscriptions/plan").json()
        assert body.get("plan_id") == "PLAN-N"
        assert sub_create_count == 0

    asyncio.run(run())


def test_n15_subscription_create_rejects_foreign_return_url():
    set_paypal_client_factory(lambda: NSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.post(
        "/api/escales/paypal/subscriptions/create",
        json={
            "return_url": "https://evil.example/?sub=return",
            "cancel_url": "https://evil.example/?sub=cancel",
        },
    )
    assert res.status_code == 422
    assert "return_url" in res.text


def test_n15_subscription_create_idempotency_key_unique_per_request():
    captured: list[str] = []

    class SubSpy(NSpy):
        def create_billing_subscription(self, **kwargs):
            captured.append(str(kwargs.get("idempotency_key") or ""))
            return super().create_billing_subscription(**kwargs)

    set_paypal_client_factory(lambda: SubSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    one = client.post(
        "/api/escales/paypal/subscriptions/create",
        json={},
        headers={"paypal-request-id": "buyer-a"},
    )
    two = client.post(
        "/api/escales/paypal/subscriptions/create",
        json={},
        headers={"paypal-request-id": "buyer-b"},
    )
    assert one.status_code == 200
    assert two.status_code == 200
    assert len(captured) == 2
    assert captured[0] != captured[1]
    assert "buyer-a" in captured[0]
    assert "buyer-b" in captured[1]
