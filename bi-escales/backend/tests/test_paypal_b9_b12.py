"""Fix lot B9–B12: authorize clock, settle timestamps, reconcile ids, stop capture on arrival."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig
from app.escales.departure_clock import run_departure_clock
from tests.review_helpers import approve_capture_review, propose_capture_review
from tests.schedule_clocks import mayotte_authorize_window_clock
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    reset_ledger,
)
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture
def api(monkeypatch):
    from tests.test_escales_router import FakePayPal

    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "b9-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class CaptureSpy:
    order_status = "APPROVED"

    def __init__(self):
        self.calls = []

    def get_order(self, order_id):
        return {"id": order_id, "status": self.order_status}

    def get_authorization(self, authorization_id, **kwargs):
        return {"id": authorization_id, "status": "CREATED"}

    def list_disputes(self):
        return {"items": []}

    def search_transactions(self, **kwargs):
        return {"transaction_details": []}

    def list_invoices(self, **kwargs):
        return {"items": []}

    def create_authorize_order(self, amount_eur, description, reference_id, **kwargs):
        return {
            "id": f"ORD-{reference_id[:8]}",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://example.test/approve"}],
        }

    def authorize_order(self, order_id, **kwargs):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "status": "COMPLETED",
            "purchase_units": [{
                "payments": {"authorizations": [{
                    "id": f"AUTH-{order_id}",
                    "expiration_time": "2099-01-01T00:00:00Z",
                }]},
            }],
        }

    def reauthorize(self, authorization_id, **kwargs):
        self.calls.append(("reauthorize", authorization_id))
        raise PayPalError(422, {"details": [{"issue": "TRANSACTION_REFUSED"}]})

    def capture_authorization(self, authorization_id, **kwargs):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP-B9", "status": "COMPLETED"}


def test_b9_authorized_at_uses_simulated_clock_and_skips_failed_reauthorize(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-12-01T08:00:00Z")
    spy = CaptureSpy()

    async def run():
        created = await create_pledge(
            amount_eur="20.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
        )
        saved = await authorize_pledge(created["_id"], spy)
        assert saved["authorized_at"] == "2026-12-01T08:00:00+00:00"
        saved["authorized_at"] = "2026-11-20T08:00:00+00:00"
        await get_ledger().save_pledge(saved)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-12-05T08:00:00Z")
        captured = await capture_pledge(saved["_id"], spy)
        assert captured["status"] == "captured"
        assert any(call[0] == "reauthorize" for call in spy.calls)
        assert any(call[0] == "capture" for call in spy.calls)

    asyncio.run(run())


def test_b10_settle_override_stamps_captured_at(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
    spy = CaptureSpy()

    async def run():
        ledger = get_ledger()
        await ledger.ensure_milestone(
            "dep-la-rochelle",
            meta={
                "capture_on": "departure",
                "departure_iso": "2026-11-20T08:00:00+00:00",
            },
        )
        created = await create_pledge(
            amount_eur="20.00",
            description="miles leg",
            milestone_id="dep-la-rochelle",
            client=spy,
        )
        await authorize_pledge(created["_id"], spy)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-20T08:00:00Z")
        await approve_capture_review("dep-la-rochelle")
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
        settle_at = __import__("datetime").datetime(2026, 11, 20, 8, 0, tzinfo=__import__("datetime").timezone.utc)
        result = await run_departure_clock(spy, now=settle_at)
        assert any(row.get("action") == "capture" for row in result["actions"])
        saved = await ledger.get_pledge(created["_id"])
        assert saved["captured_at"] == "2026-11-20T08:00:00+00:00"
        assert saved["captured_at"] != "2026-11-12T08:00:00+00:00"

    asyncio.run(run())


def test_b11_reconcile_matches_on_capture_id():
    async def run():
        class TxnClient:
            def search_transactions(self, **kwargs):
                assert "start_date" in kwargs
                return {
                    "transaction_details": [{
                        "transaction_info": {
                            "transaction_id": "CAP-RECON",
                            "transaction_amount": {"value": "12.50"},
                        },
                    }],
                }

        report = await reconcile_paypal_ledger(
            start_date="2026-11-04T00:00:00Z",
            end_date="2026-11-05T00:00:00Z",
            client=TxnClient(),
            finance_entries=[{
                "_id": "fin1",
                "kind": "pledge_captured",
                "capture_id": "CAP-RECON",
                "pledge_id": "p1",
                "amount_eur": "12.50",
                "at": "2026-11-04T10:00:00+00:00",
            }],
            lang="en",
        )
        assert report["match_key"] == "capture_id"
        assert report["matched"][0]["capture_id"] == "CAP-RECON"
        assert report["sandbox_reporting_lag_hours"] == 3
        assert "3 hour" in report["note"].lower() or "3 hours" in report["note"].lower()

    asyncio.run(run())


def test_b12_stop_mile_pledge_settles_on_arrival(monkeypatch):
    """Stop-level miles: captured on boat arrival at the stop (7488f15); void if cancelled."""
    monkeypatch.setenv("ESCALES_CLOCK_NOW", mayotte_authorize_window_clock())
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "0")
    spy = CaptureSpy()

    async def run():
        from app.escales.naviguide_bridge import resolve_milestone, resolve_schedule_milestone

        stop = resolve_milestone("dep-dzaoudzi-mayotte")
        assert stop
        doc = await resolve_schedule_milestone(stop)
        created = await create_pledge(
            amount_eur="5.00",
            description="miles Mayotte",
            milestone_id="dep-dzaoudzi-mayotte",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        early = await run_departure_clock(spy)
        assert early["actions"][0]["action"] == "wait"
        arrival_raw = str(doc["meta"]["arrival_iso"])
        text = arrival_raw.replace("Z", "+00:00") if arrival_raw.endswith("Z") else arrival_raw
        arrival_day = __import__("datetime").datetime.fromisoformat(text)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", arrival_day.isoformat())
        await approve_capture_review("dep-dzaoudzi-mayotte")
        done = await run_departure_clock(spy, now=arrival_day)
        assert done["actions"][0]["action"] == "capture"

    asyncio.run(run())


def test_b12_cancelled_stop_voids_mile_pledge(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-20T08:00:00Z")
    spy = CaptureSpy()
    spy.void_authorization = lambda auth_id, **k: {"id": auth_id}

    async def run():
        created = await create_pledge(
            amount_eur="5.00",
            description="miles cancel",
            milestone_id="dep-la-rochelle",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        ledger = get_ledger()
        await ledger.append_evidence("dep-la-rochelle", {
            "met": False,
            "facts": {"cancelled": True},
            "recorded_at": "2026-11-20T08:00:00+00:00",
        })
        result = await run_departure_clock(spy)
        assert result["actions"][0]["action"] == "void"

    asyncio.run(run())


def test_b10_clock_settle_api_uses_override_now(api, monkeypatch):
    import asyncio

    from app.escales.ledger import get_ledger
    from app.escales.naviguide_bridge import resolve_milestone

    client, fake = api
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
    sailing = resolve_milestone("dep-la-rochelle")
    assert sailing
    departure = "2026-11-20T08:00:00+00:00"

    async def stamp():
        await get_ledger().ensure_milestone(sailing, meta={
            "capture_on": "departure",
            "departure_iso": departure,
        })

    asyncio.run(stamp())
    created = client.post("/api/escales/pledges", json={
        "amount_eur": "20.00",
        "description": "settle override",
        "milestone_id": "dep-la-rochelle",
    })
    assert created.status_code == 200, created.text
    auth = client.post(f"/api/escales/pledges/{created.json()['id']}/authorize")
    assert auth.status_code == 200, auth.text
    monkeypatch.setenv("ESCALES_CLOCK_NOW", departure)
    asyncio.run(propose_capture_review(sailing))
    approve = client.post(
        "/api/escales/milestones/dep-la-rochelle/captain-review/approve",
        headers={"x-admin-key": "test-admin-key"},
    )
    assert approve.status_code == 200, approve.text
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
    settle = client.post(
        "/api/escales/clock/settle",
        headers={"x-admin-key": "test-admin-key"},
        json={"now": "2026-11-20T08:00:00+00:00"},
    )
    assert settle.status_code == 200, settle.text
    actions = settle.json()["settled"]["actions"]
    assert any(row["pledge_id"] == created.json()["id"] and row["action"] == "capture" for row in actions)
    body = client.get(f"/api/escales/pledges/{created.json()['id']}", headers={"x-admin-key": "test-admin-key"})
    assert body.json()["captured_at"] == "2026-11-20T08:00:00+00:00"


def test_reconcile_route_includes_lag_note():
    class TxnClient:
        def search_transactions(self, **kwargs):
            return {"transaction_details": []}

    set_paypal_client_factory(lambda: TxnClient())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get(
        "/api/escales/paypal/reconcile",
        params={"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-08T00:00:00Z", "lang": "en"},
        headers={"x-admin-key": "b9-admin"},
    )
    assert response.status_code == 200
    assert response.json()["match_key"] == "capture_id"
    assert "lag" in response.json()["note"].lower()


def test_b12_canonical_capture_rule_wording():
    from app.escales.captain import _public_rule
    from app.escales.departure_clock import CAPTURE_RULES_EN, CAPTURE_RULES_FR

    assert "Project crowdfunding is collected immediately" in CAPTURE_RULES_EN
    assert "project gifts" not in CAPTURE_RULES_EN.lower()
    assert "stop departure" not in CAPTURE_RULES_EN.lower()
    assert CAPTURE_RULES_EN in _public_rule("en")
    assert CAPTURE_RULES_FR in _public_rule("fr")
