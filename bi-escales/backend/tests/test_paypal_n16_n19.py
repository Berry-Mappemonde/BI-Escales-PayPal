"""Lot N16–N19: crew plan hydration, captain lang (router), subscription approve on return."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.paypal_subscriptions import (
    CREW_PLAN_NAME,
    CREW_PRODUCT_NAME,
    ensure_crew_supporter_catalog,
    resolve_crew_supporter_plan_id,
)
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


class HydrateSpy(NSpy):
    def __init__(self):
        self.create_product_calls = 0
        self.create_plan_calls = 0

    def create_billing_product(self, **kwargs):
        self.create_product_calls += 1
        return super().create_billing_product(**kwargs)

    def create_billing_plan(self, **kwargs):
        self.create_plan_calls += 1
        return super().create_billing_plan(**kwargs)

    def list_billing_products(self, **kwargs):
        return {"products": [{"id": "PROD-EXIST", "name": CREW_PRODUCT_NAME}]}

    def list_billing_plans(self, **kwargs):
        return {"plans": [{"id": "PLAN-EXIST", "name": CREW_PLAN_NAME}]}


def test_n16_public_plan_route_hydrates_from_paypal_catalog_without_create():
    async def run():
        spy = HydrateSpy()
        set_paypal_client_factory(lambda: spy)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        body = client.get("/api/escales/paypal/subscriptions/plan").json()
        assert body.get("plan_id") == "PLAN-EXIST"
        assert spy.create_product_calls == 0
        assert spy.create_plan_calls == 0
        again = client.get("/api/escales/paypal/subscriptions/plan").json()
        assert again.get("plan_id") == "PLAN-EXIST"

    asyncio.run(run())


def test_n16_resolve_does_not_create_when_catalog_missing_on_paypal():
    async def run():
        spy = NSpy()
        set_paypal_client_factory(lambda: spy)
        plan_id = await resolve_crew_supporter_plan_id(spy)
        assert plan_id is None

    asyncio.run(run())


def test_n19_subscription_approve_requires_active_paypal_status():
    asyncio.run(ensure_crew_supporter_catalog(NSpy()))
    spy = NSpy()

    class PendingSpy(NSpy):
        def get_subscription(self, subscription_id):
            row = super().get_subscription(subscription_id)
            row["status"] = "APPROVAL_PENDING"
            return row

    set_paypal_client_factory(lambda: PendingSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.post(
        "/api/escales/paypal/subscriptions/approve",
        json={"subscription_id": "I-BUYER-1", "plan_id": "PLAN-N"},
    )
    assert res.status_code == 422
    assert "ACTIVE" in res.text or "approval" in res.text.lower()
