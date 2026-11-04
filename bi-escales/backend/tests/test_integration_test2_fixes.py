"""Fixes from test2 run on integration 7db3a42 (subscription idempotency, LLM JSON, approve gate)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales.paypal_subscriptions import ensure_crew_supporter_catalog, list_subscriptions_local
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


def test_subscription_create_replays_cached_response_for_same_paypal_request_id():
    class CountingSpy(NSpy):
        def __init__(self):
            self.calls = 0
            self.keys: list[str] = []

        def create_billing_subscription(self, **kwargs):
            self.calls += 1
            self.keys.append(str(kwargs.get("idempotency_key") or ""))
            return {
                "id": f"I-REPLAY-{self.calls}",
                "status": "APPROVAL_PENDING",
                "plan_id": kwargs.get("plan_id"),
                "links": [{"rel": "approve", "href": "https://paypal.test/approve"}],
            }

    spy = CountingSpy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"paypal-request-id": "same-buyer-key"}
    first = client.post("/api/escales/paypal/subscriptions/create", json={}, headers=headers)
    second = client.post("/api/escales/paypal/subscriptions/create", json={}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert spy.calls == 1
    assert spy.keys == ["same-buyer-key"]
    assert first.json()["subscription_id"] == second.json()["subscription_id"] == "I-REPLAY-1"


def test_subscription_create_forwards_distinct_paypal_request_ids():
    captured: list[str] = []

    class SubSpy(NSpy):
        def create_billing_subscription(self, **kwargs):
            captured.append(str(kwargs.get("idempotency_key") or ""))
            return super().create_billing_subscription(**kwargs)

    set_paypal_client_factory(lambda: SubSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.post(
        "/api/escales/paypal/subscriptions/create",
        json={},
        headers={"paypal-request-id": "buyer-a"},
    )
    client.post(
        "/api/escales/paypal/subscriptions/create",
        json={},
        headers={"paypal-request-id": "buyer-b"},
    )
    assert captured == ["buyer-a", "buyer-b"]


def test_parse_json_object_strips_reasoning_fence_and_prose():
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    raw = (
        open_tag
        + "planning the treasurer answer"
        + close_tag
        + '\nHere is the JSON:\n```json\n{"proposal":"wait","reason":"hold"}\n```'
    )
    data = llm.parse_json_object(raw)
    assert data == {"proposal": "wait", "reason": "hold"}
    assert llm.advisory_matches_schema(data)


def test_subscription_approve_rejects_approval_pending():
    class PendingSpy(NSpy):
        def get_subscription(self, subscription_id):
            return {
                "id": subscription_id,
                "plan_id": "PLAN-N",
                "status": "APPROVAL_PENDING",
            }

    async def run():
        await ensure_crew_supporter_catalog(NSpy())
        set_paypal_client_factory(lambda: PendingSpy())
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        res = client.post(
            "/api/escales/paypal/subscriptions/approve",
            json={"subscription_id": "I-PENDING", "plan_id": "PLAN-N"},
        )
        assert res.status_code == 422
        assert "APPROVAL_PENDING" in res.text
        rows = await list_subscriptions_local()
        assert rows == []

    asyncio.run(run())
