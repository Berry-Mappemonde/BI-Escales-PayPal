"""Judge-visible fixes lot (Hamid QA 3199227), base 5c7f750."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bi_marinas_catalog import bundled_escale_entry, mooring_marinas_to_geojson
from app.escales.captain import chat, model_display_label
from app.escales.departure_clock import run_departure_clock
from app.escales.milestones import captain_review_approved, record_captain_review_approval
from app.escales.paypal_subscriptions import CREW_PLAN_ID_EN_FALLBACK, resolve_crew_supporter_plan_id
from app.escales.pledges import authorize_pledge, create_pledge, reset_ledger
from app.escales.toolkit_tools import ReadOnlyTools
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "judge-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class PlanSpy:
    def list_products(self, **_k):
        return {"products": []}

    def list_plans(self, **_k):
        return {"plans": []}


def test_en_crew_plan_fallback_when_catalog_missing(monkeypatch):
    """With no catalog the app offers no plan. The old hard-coded id is the 5 EUR per
    month plan: it must not be sold under the "10 EUR per year" label (it still verifies)."""
    async def empty_hydrate(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.escales.paypal_subscriptions._hydrate_lang_from_paypal",
        empty_hydrate,
    )

    async def body():
        from app.escales.paypal_subscriptions import legacy_crew_plan_ids

        plan_id = await resolve_crew_supporter_plan_id(PlanSpy(), lang="en")
        assert plan_id is None
        assert CREW_PLAN_ID_EN_FALLBACK in await legacy_crew_plan_ids()

    asyncio.run(body())


def test_bundled_escale_resolves_short_city_name():
    full = bundled_escale_entry("Pointe-à-Pitre (Guadeloupe)")
    short = bundled_escale_entry("Pointe-à-Pitre")
    assert full.get("sections")
    assert short.get("sections") == full.get("sections")


def test_geojson_feature_includes_rejection_and_source():
    row = {
        "name": "Test",
        "lat": 1.0,
        "lon": 2.0,
        "osm_id": "way/1",
        "maps_place_rejected": "suspicious_name",
        "source": "bi_export",
    }
    fc = mooring_marinas_to_geojson([row])
    props = fc["features"][0]["properties"]
    assert props["maps_place_rejected"] == "suspicious_name"
    assert props["source"] == "bi_export"


def test_n8_settle_waits_without_review_approval(monkeypatch):
    from tests.test_paypal_b9_b12 import CaptureSpy

    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-12-01T08:00:00Z")
    spy = CaptureSpy()

    async def run():
        from app.escales.naviguide_bridge import resolve_milestone
        from app.escales.pledges import get_ledger

        sailing = resolve_milestone("dep-la-rochelle")
        assert sailing
        await get_ledger().ensure_milestone(
            sailing,
            meta={"capture_on": "departure", "departure_iso": "2026-11-20T08:00:00+00:00"},
        )
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
        )
        await authorize_pledge(created["_id"], spy)
        assert await captain_review_approved("dep-la-rochelle") is False
        result = await run_departure_clock(spy)
        assert any(row.get("action") == "await_review_approval" for row in result["actions"])

    asyncio.run(run())


def test_model_display_label_nim():
    label = model_display_label({"provider": "nim", "model": "private/nvidia/nemotron-3.5-super-120b-a12b"})
    assert label.startswith("NVIDIA NIM")


def test_en_list_paypal_transactions_matches_readonly_pattern():
    from app.escales.captain import _is_paypal_readonly_question

    assert _is_paypal_readonly_question("Please list recent PayPal transactions for the treasurer")


def test_readonly_tools_client_field_direct():
    class Client:
        def get_order(self, _oid):
            return {}

        def get_authorization(self, _aid):
            return {}

        def list_disputes(self):
            return {"items": []}

        def search_transactions(self, **kwargs):
            return {"transaction_details": []}

        def list_invoices(self, **_k):
            return {"items": []}

    reader = ReadOnlyTools(Client())
    assert reader.uses_toolkit is False


def test_pledge_status_question_with_admin_key(monkeypatch):
    from tests.test_paypal_b9_b12 import CaptureSpy

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)
    set_paypal_client_factory(lambda: CaptureSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def seed():
        spy = CaptureSpy()
        doc = await create_pledge(
            amount_eur="3.00",
            description="test",
            milestone_id="dep-mayotte",
            client=spy,
        )
        await authorize_pledge(doc["_id"], spy)
        return doc["_id"]

    pledge_id = asyncio.run(seed())
    res = client.post(
        "/api/escales/captain/chat",
        json={"message": "What is the status of my pledge?", "lang": "en"},
        headers={"x-admin-key": "judge-admin"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert pledge_id in body["reply"]
    assert body["paypal_tools"]["client"] == "direct"
