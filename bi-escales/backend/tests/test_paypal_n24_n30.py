"""Fix lot N24–N30 (87338a9 follow-up)."""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import simulated_now
from app.escales.departure_clock import refuse_early_capture
from app.escales.ledger import list_finance_entries, record_finance, to_public_fund
from app.escales.paypal_subscriptions import (
    CREW_PLAN_NAME,
    CREW_PRODUCT_NAME,
    SUBSCRIPTION_CREATE_CACHE_KIND,
    SUBSCRIPTION_CREATE_CACHE_MAX,
    approve_crew_subscription,
    create_crew_subscription,
    ensure_crew_supporter_catalog,
    resolve_crew_supporter_plan_id,
)
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, reset_ledger
from app.routers.escales import router, set_paypal_client_factory, webhooks_router
from tests.test_escales_pledges import Spy
from tests.test_escales_router import FakePayPal as RouterFakePayPal
from tests.test_escales_webhooks import HEADERS
from tests.test_paypal_n1_n5 import NSpy


class WebhookCapablePayPal(RouterFakePayPal):
    def __init__(self):
        super().__init__()
        self.verify_calls = 0

    def verify_webhook_signature(self, **kwargs):
        self.verify_calls += 1
        assert kwargs["webhook_id"] == "WH-DEMO"
        return {"verification_status": "SUCCESS"}


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-DEMO")
    fake = WebhookCapablePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    app.include_router(webhooks_router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)


def test_n24_public_plan_route_is_read_only_and_paginates_products():
    class PageSpy(NSpy):
        def __init__(self):
            super().__init__()
            self.create_product_calls = 0
            self.pages_seen: list[int] = []

        def create_billing_product(self, **kwargs):
            self.create_product_calls += 1
            return super().create_billing_product(**kwargs)

        def list_billing_products(self, *, page=1, page_size=20):
            self.pages_seen.append(int(page))
            if page == 1:
                return {
                    "products": [{"id": "OTHER", "name": "Other product"}],
                    "total_pages": 2,
                }
            return {
                "products": [{"id": "PROD-CREW", "name": CREW_PRODUCT_NAME}],
                "total_pages": 2,
            }

        def list_billing_plans(self, **kwargs):
            return {"plans": [{"id": "PLAN-CREW", "name": CREW_PLAN_NAME}]}

        def iter_billing_product_pages(self, **kwargs):
            for page in (1, 2):
                yield self.list_billing_products(page=page)

    async def run():
        spy = PageSpy()
        set_paypal_client_factory(lambda: spy)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        body = client.get("/api/escales/paypal/subscriptions/plan", params={"lang": "en"}).json()
        assert body.get("plan_id") == "PLAN-CREW"
        assert spy.create_product_calls == 0
        assert spy.pages_seen == [1, 2]

    asyncio.run(run())


def test_n25_subscription_replay_cache_keys_body_and_stays_bounded():
    class SubSpy(NSpy):
        def __init__(self):
            super().__init__()
            self.n = 0

        def create_billing_subscription(self, **kwargs):
            self.n += 1
            body = super().create_billing_subscription(**kwargs)
            body["id"] = f"I-BUYER-{self.n}"
            return body

    async def run():
        spy = SubSpy()
        await ensure_crew_supporter_catalog(spy)
        first = await create_crew_subscription(
            spy,
            return_url="https://app.example/?sub=return",
            cancel_url="https://app.example/?sub=cancel",
            client_key="buyer-1",
        )
        second = await create_crew_subscription(
            spy,
            return_url="https://app.example/?sub=return",
            cancel_url="https://app.example/?sub=cancel",
            client_key="buyer-1",
        )
        assert second["subscription_id"] == first["subscription_id"]
        different = await create_crew_subscription(
            spy,
            return_url="https://app.example/other?sub=return",
            cancel_url="https://app.example/other?sub=cancel",
            client_key="buyer-1",
        )
        assert different["subscription_id"] != first["subscription_id"]
        cache_rows = [
            row for row in await list_finance_entries()
            if row.get("kind") == SUBSCRIPTION_CREATE_CACHE_KIND
        ]
        assert len(cache_rows) == 2
        assert len(cache_rows) <= SUBSCRIPTION_CREATE_CACHE_MAX

    asyncio.run(run())


def test_n26_subscription_approve_rejects_foreign_plan_id():
    class WrongPlanSpy(NSpy):
        def get_subscription(self, subscription_id):
            row = super().get_subscription(subscription_id)
            row["plan_id"] = "PLAN-WRONG"
            return row

    async def run():
        spy = WrongPlanSpy()
        await ensure_crew_supporter_catalog(spy)
        with pytest.raises(ValueError, match="Crew supporter plan"):
            await approve_crew_subscription(
                spy,
                subscription_id="I-BUYER-1",
                plan_id="PLAN-WRONG",
            )

    asyncio.run(run())


def test_n27_admin_reauthorize_uses_simulated_clock_for_honor_period(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-01T12:00:00Z")
    monkeypatch.delenv("ESCALES_ENV", raising=False)

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def run():
        spy = Spy()
        set_paypal_client_factory(lambda: spy)
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-mayotte",
            client=spy,
        )
        authorized = await authorize_pledge(created["_id"], spy)
        authorized["authorized_at"] = (
            simulated_now() - dt.timedelta(days=5)
        ).replace(microsecond=0).isoformat()
        from app.escales.ledger import get_ledger
        from app.escales.pledges import admin_reauthorize_pledge

        await get_ledger().save_pledge(authorized)
        saved = await admin_reauthorize_pledge(authorized["_id"], spy)
        assert "reauthorized" in saved.get("history", [])

    asyncio.run(run())


def test_n28_capture_before_arrival_hour_is_refused(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def run():
        spy = Spy()
        created = await create_pledge(
            amount_eur="1.00",
            description="miles",
            milestone_id="dep-mayotte",
            client=spy,
            kind="mile",
            target_id="mayotte",
        )
        authorized = await authorize_pledge(created["_id"], spy)
        from app.escales.naviguide_bridge import resolve_schedule_milestone

        stop = await resolve_schedule_milestone("dep-mayotte")
        arrival = dt.datetime.fromisoformat(
            str(stop["meta"]["arrival_iso"]).replace("Z", "+00:00"),
        )
        same_day_early = arrival - dt.timedelta(hours=1)
        with pytest.raises(ValueError, match="capture is before"):
            await refuse_early_capture(authorized, now=same_day_early)
        await capture_pledge(authorized["_id"], spy, effective_at=arrival)

    asyncio.run(run())


def test_n29_fr_pledge_intent_is_french():
    import json
    from pathlib import Path

    fr = json.loads(
        (Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "locales" / "fr.json").read_text(
            encoding="utf-8",
        ),
    )
    intent = fr["pledge"]["intent"]
    assert "AUTHORIZE" in intent
    assert "sandbox PayPal" in intent
    assert "Intent AUTHORIZE" in intent


def test_n30_public_fund_includes_refunded_eur():
    public = to_public_fund(
        {
            "milestone_id": "mayotte",
            "currency": "EUR",
            "income_eur": "10.00",
            "captured_eur": "10.00",
            "authorized_eur": "0.00",
            "spending_eur": "1.00",
            "refunded_eur": "2.50",
            "balance_eur": "6.50",
            "overdrawn": False,
        },
    )
    assert public["refunded_eur"] == "2.50"


def test_n31_french_price_label_on_suggested_pledge_and_create_response(api, monkeypatch):
    from app.escales.captain import suggest_pledge

    from tests.test_escales_router import NEAR_MAYOTTE_CLOCK

    monkeypatch.setenv("ESCALES_CLOCK_NOW", NEAR_MAYOTTE_CLOCK)
    suggested = suggest_pledge("Je parraine 5 milles près de Mayotte", lang="fr")
    assert suggested is not None
    assert suggested["price_label"] == "prix simulé"

    client, _fake = api
    payload = {
        "amount_eur": "12.00",
        "description": "milles parrainés",
        "milestone_id": "dep-mayotte",
        "kind": "mile",
        "target_id": "mayotte",
        "lang": "fr",
    }
    response = client.post(
        "/api/escales/pledges",
        headers={"PayPal-Request-Id": "n31-fr", "Content-Type": "application/json"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price_label"] == "prix simulé"
    assert body["simulated_price"]["label"] == "prix fixe"


def test_n32_refund_webhook_links_pledge_via_capture_id(api):
    import asyncio
    import json

    from app.escales.ledger import get_ledger, list_finance_entries

    async def seed():
        await get_ledger().insert_pledge_once(
            {
                "_id": "p-refund-cap",
                "status": "captured",
                "intent": "AUTHORIZE",
                "payment_mode": "AUTHORIZE",
                "currency": "EUR",
                "amount_eur": "10.00",
                "description": "miles",
                "milestone_id": "dep-mayotte",
                "kind": "mile",
                "target_id": "mayotte",
                "capture_id": "CAP-REF-N32",
                "history": ["created", "captured"],
            },
        )

    asyncio.run(seed())
    client, _fake = api
    resource = {
        "id": "CAP-REF-N32",
        "status": "REFUNDED",
        "links": [
            {
                "href": "https://api.sandbox.paypal.com/v2/payments/captures/CAP-REF-N32",
                "rel": "self",
            },
        ],
    }
    headers = dict(HEADERS)
    headers["PAYPAL-TRANSMISSION-ID"] = "T-N32-REFUND"
    payload = {"id": "evt-n32", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": resource}
    response = client.post(
        "/api/escales/webhooks/paypal",
        headers=headers,
        content=json.dumps(payload),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pledge_id"] == "p-refund-cap"
    entries = asyncio.run(list_finance_entries())
    received = next(
        row
        for row in entries
        if row["kind"] == "webhook_received" and row.get("event_type") == "PAYMENT.CAPTURE.REFUNDED"
    )
    assert received["pledge_id"] == "p-refund-cap"
    refunded = next(row for row in entries if row["kind"] == "webhook_capture_refunded")
    assert refunded["pledge_id"] == "p-refund-cap"
    assert refunded["capture_id"] == "CAP-REF-N32"
    saved = asyncio.run(get_ledger().get_pledge("p-refund-cap"))
    assert saved["status"] == "refunded"
