"""Follow-up N8, N9, N10: refund timestamps, reconcile window, schedule resolve, arrival capture."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.departure_clock import run_departure_clock
from tests.review_helpers import approve_capture_review
from tests.schedule_clocks import mayotte_authorize_window_clock
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    refund_pledge,
    reset_ledger,
    resolve_payment_mode,
)
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n810-admin")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class MoneySpy:
    def create_authorize_order(self, amount_eur, description, reference_id, **kwargs):
        return {
            "id": f"ORD-{reference_id[:8]}",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://example.test/approve"}],
        }

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def create_order(self, **kwargs):
        return {"id": "ORD-1", "links": [{"rel": "approve", "href": "https://paypal.test/approve"}]}

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": "AUTH-1", "expiration_time": "2099-01-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, auth_id, **kwargs):
        return {"id": "CAP-1", "status": "COMPLETED"}

    def reauthorize(self, auth_id, **kwargs):
        return {"id": auth_id, "expiration_time": "2099-01-01T00:00:00Z"}

    def refund_capture(self, capture_id, **kwargs):
        return {"id": "RF-1", "status": "COMPLETED"}


def test_n8_refunded_at_not_before_captured_at_under_pinned_clock(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    spy = MoneySpy()

    async def run():
        created = await create_pledge(
            amount_eur="10.00",
            description="refund clock",
            milestone_id="dep-la-rochelle",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        capture_at = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
        captured = await capture_pledge(created["_id"], spy, effective_at=capture_at)
        assert captured["captured_at"].startswith("2026-11-20")
        refunded = await refund_pledge(created["_id"], spy)
        assert refunded["refunded_at"] >= captured["captured_at"]

    asyncio.run(run())


def test_n10_reconcile_matches_all_ledger_captures_by_capture_id():
    async def run():
        class TxnClient:
            def search_transactions(self, **kwargs):
                return {
                    "transaction_details": [{
                        "transaction_info": {
                            "transaction_id": "CAP-OLD",
                            "transaction_amount": {"value": "1.00"},
                        },
                    }],
                }

        report = await reconcile_paypal_ledger(
            start_date="2026-11-04T00:00:00Z",
            end_date="2026-11-05T00:00:00Z",
            client=TxnClient(),
            finance_entries=[
                {
                    "_id": "old",
                    "kind": "pledge_captured",
                    "capture_id": "CAP-OLD",
                    "pledge_id": "p-old",
                    "amount_eur": "1.00",
                    "at": "2020-01-01T00:00:00+00:00",
                },
                {
                    "_id": "in",
                    "kind": "pledge_captured",
                    "capture_id": "CAP-IN",
                    "pledge_id": "p-in",
                    "amount_eur": "2.00",
                    "at": "2026-11-04T12:00:00+00:00",
                },
            ],
        )
        assert report["searched_start_date"] == report["start_date"]
        assert report["ledger_capture_count"] == 2
        assert len(report["matched"]) == 1
        assert report["matched"][0]["capture_id"] == "CAP-OLD"
        assert len(report["ledger_only"]) == 1
        assert report["ledger_only"][0]["capture_id"] == "CAP-IN"

    asyncio.run(run())


def test_n9_settle_and_payment_mode_resolve_stops_without_milestone_sync(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-19T08:00:00+00:00")
    spy = MoneySpy()

    async def run():
        from app.escales.naviguide_bridge import resolve_milestone, resolve_schedule_milestone

        sailing = resolve_milestone("dep-dzaoudzi-mayotte")
        assert sailing
        assert await get_ledger().get_milestone(sailing) is None
        mode = await resolve_payment_mode(sailing)
        assert mode in {"AUTHORIZE", "VAULT"}
        doc = await get_ledger().get_milestone(sailing)
        assert doc is not None
        assert doc["meta"]["capture_on"] == "arrival"

        monkeypatch.setenv("ESCALES_CLOCK_NOW", mayotte_authorize_window_clock())
        monkeypatch.setenv("ESCALES_VAULT_ENABLED", "0")
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-dzaoudzi-mayotte",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        before = await run_departure_clock(spy)
        assert before["actions"][0]["action"] == "wait"
        arrival_raw = str(doc["meta"]["arrival_iso"])
        arrival_day = datetime.fromisoformat(arrival_raw.replace("Z", "+00:00"))
        monkeypatch.setenv("ESCALES_CLOCK_NOW", arrival_day.isoformat())
        await approve_capture_review("dep-dzaoudzi-mayotte")
        done = await run_departure_clock(spy, now=arrival_day)
        assert done["actions"][0]["action"] == "capture"

    asyncio.run(run())


def test_capture_rule_stop_miles_use_arrival_capture_on(monkeypatch):
    """Stop-level pledges use capture_on=arrival (7488f15 wording in departure_clock)."""
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    spy = MoneySpy()

    async def run():
        from app.escales.naviguide_bridge import resolve_milestone

        stop = resolve_milestone("dep-la-rochelle")
        assert stop
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            kind="mile",
        )
        assert created["milestone_id"] == stop
        doc = await get_ledger().get_milestone(stop)
        assert doc["meta"]["capture_on"] == "arrival"

    asyncio.run(run())
