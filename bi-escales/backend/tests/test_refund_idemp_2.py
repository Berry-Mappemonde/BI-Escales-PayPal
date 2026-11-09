"""REFUND-IDEMP-2: reject silent no-op when fully refunded with a new request_key."""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import parse_clock_moment
from app.escales.pledges import (
    PledgeAlreadyFullyRefunded,
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    refund_pledge,
    reset_ledger,
)
from tests.schedule_clocks import mayotte_authorize_window_clock, near_mayotte_clock


def _authorized_at_day_before_capture() -> str:
    moment = parse_clock_moment(near_mayotte_clock()) - dt.timedelta(days=1)
    return moment.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", mayotte_authorize_window_clock())
    reset_ledger()
    yield
    reset_ledger()


class CountingPayPal:
    def __init__(self):
        self.refund_n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        return {
            "id": "ORD-RID2",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORD-RID2"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{"id": "AUTH-RID2", "expiration_time": "2099-01-01T00:00:00Z"}],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        return {"id": "CAP-RID2", "status": "COMPLETED"}

    def refund_capture(self, capture_id, *, amount_eur=None, idempotency_key=None, **kwargs):
        self.refund_n += 1
        return {"id": "REF-RID2-1", "status": "COMPLETED"}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def reauthorize(self, authorization_id, **kwargs):
        return {"id": authorization_id, "expiration_time": "2099-01-01T00:00:00Z"}


async def _captured(client: CountingPayPal, monkeypatch):
    created = await create_pledge(
        amount_eur="10.00",
        description="refund idemp 2",
        milestone_id="dep-mayotte",
        client=client,
        client_key="rid2",
    )
    await authorize_pledge(created["_id"], client)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", near_mayotte_clock())
    pledge = await get_ledger().get_pledge(created["_id"])
    assert pledge is not None
    pledge["authorized_at"] = _authorized_at_day_before_capture()
    await get_ledger().save_pledge(pledge)
    captured = await capture_pledge(created["_id"], client)
    assert captured["status"] == "captured"
    return created["_id"]


def test_full_refund_then_new_request_key_raises_409(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        first = await refund_pledge(
            pledge_id,
            client,
            amount_eur="10.00",
            request_key="treasurer-full",
        )
        assert client.refund_n == 1
        assert first["status"] == "refunded"
        with pytest.raises(PledgeAlreadyFullyRefunded) as err:
            await refund_pledge(
                pledge_id,
                client,
                amount_eur="10.00",
                request_key="treasurer-extra",
            )
        assert client.refund_n == 1
        assert err.value.paypal_refund_id == "REF-RID2-1"

    asyncio.run(run())


def test_full_refund_then_same_request_key_replays_without_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        first = await refund_pledge(
            pledge_id,
            client,
            amount_eur="10.00",
            request_key="treasurer-full",
        )
        second = await refund_pledge(
            pledge_id,
            client,
            amount_eur="10.00",
            request_key="treasurer-full",
        )
        assert client.refund_n == 1
        assert first["refund_id"] == second["refund_id"] == "REF-RID2-1"

    asyncio.run(run())


def test_partial_then_remaining_refund_with_new_key_still_calls_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)

        def refund_capture(capture_id, *, amount_eur=None, idempotency_key=None, **kwargs):
            client.refund_n += 1
            return {"id": f"REF-RID2-{client.refund_n}", "status": "COMPLETED"}

        client.refund_capture = refund_capture

        await refund_pledge(pledge_id, client, amount_eur="4.00", request_key="part-a")
        saved = await refund_pledge(pledge_id, client, amount_eur="6.00", request_key="part-b")
        assert client.refund_n == 2
        assert saved["status"] == "refunded"

    asyncio.run(run())


def test_http_409_body_includes_paypal_refund_id(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers.escales import router, set_paypal_client_factory
    from tests.review_helpers import approve_capture_review

    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", mayotte_authorize_window_clock())
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "rid2-admin")
    client_pp = CountingPayPal()
    set_paypal_client_factory(lambda: client_pp)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as http:
            created = http.post(
                "/api/escales/pledges",
                json={
                    "amount_eur": "10.00",
                    "description": "http 409 shape",
                    "milestone_id": "dep-mayotte",
                },
                headers={"PayPal-Request-Id": "rid2-create"},
            )
            assert created.status_code == 200, created.text
            pledge_id = created.json()["id"]
            assert http.post(f"/api/escales/pledges/{pledge_id}/authorize").status_code == 200
            monkeypatch.setenv("ESCALES_CLOCK_NOW", near_mayotte_clock())
            pledge_doc = asyncio.run(get_ledger().get_pledge(pledge_id))
            assert pledge_doc is not None
            pledge_doc["authorized_at"] = _authorized_at_day_before_capture()
            asyncio.run(get_ledger().save_pledge(pledge_doc))
            asyncio.run(approve_capture_review("dep-mayotte"))
            cap = http.post(
                f"/api/escales/pledges/{pledge_id}/capture",
                headers={"x-admin-key": "rid2-admin"},
            )
            assert cap.status_code == 200, cap.text
            headers = {"x-admin-key": "rid2-admin"}
            full = http.post(
                f"/api/escales/pledges/{pledge_id}/refund",
                headers=headers,
                json={"amount_eur": "10.00", "request_key": "once"},
            )
            assert full.status_code == 200, full.text
            dup = http.post(
                f"/api/escales/pledges/{pledge_id}/refund",
                headers=headers,
                json={"amount_eur": "10.00", "request_key": "again"},
            )
            assert dup.status_code == 409, dup.text
            body = dup.json()
            assert body["detail"] == "pledge already fully refunded"
            assert body["paypal_refund_id"] == "REF-RID2-1"
            assert client_pp.refund_n == 1
    finally:
        set_paypal_client_factory(None)
        reset_ledger()
