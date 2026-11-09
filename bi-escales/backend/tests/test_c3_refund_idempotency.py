"""C3 refund idempotency: request_key, amount-key 409, webhook-first."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import (
    RefundRequestKeyRequired,
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    reconcile_refund_on_pledge,
    refund_pledge,
    refunded_amount_from_pledge,
    reset_ledger,
    _normalize_refunds,
)


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


class CountingPayPal:
    def __init__(self):
        self.refund_n = 0
        self.refund_keys: list[str] = []

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        return {
            "id": "ORD-C3",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORD-C3"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{"id": "AUTH-C3", "expiration_time": "2099-01-01T00:00:00Z"}],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        return {"id": "CAP-C3", "status": "COMPLETED"}

    def refund_capture(self, capture_id, *, amount_eur=None, idempotency_key=None, **kwargs):
        self.refund_keys.append(str(idempotency_key or ""))
        self.refund_n += 1
        return {"id": f"REF-C3-{self.refund_n}", "status": "COMPLETED"}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def reauthorize(self, authorization_id, **kwargs):
        return {
            "id": authorization_id,
            "expiration_time": "2099-01-01T00:00:00Z",
        }


async def _captured(client: CountingPayPal, monkeypatch):
    created = await create_pledge(
        amount_eur="10.00",
        description="c3 refund",
        milestone_id="dep-mayotte",
        client=client,
        client_key="c3-refund",
    )
    await authorize_pledge(created["_id"], client)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    pledge = await get_ledger().get_pledge(created["_id"])
    assert pledge is not None
    pledge["authorized_at"] = "2027-06-11T08:00:00+00:00"
    await get_ledger().save_pledge(pledge)
    captured = await capture_pledge(created["_id"], client)
    assert captured["status"] == "captured"
    return created["_id"]


def test_webhook_refund_then_api_skips_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        await reconcile_refund_on_pledge(
            pledge,
            refund_id="REF-WH-C3",
            amount_eur="10.00",
            status="COMPLETED",
        )
        saved = await refund_pledge(
            pledge_id,
            client,
            paypal_refund_id="REF-WH-C3",
        )
        assert client.refund_n == 0
        assert saved["status"] == "refunded"
        assert len(_normalize_refunds(saved)) == 1

    asyncio.run(run())


def test_same_request_key_one_paypal_call_one_row(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        first = await refund_pledge(
            pledge_id,
            client,
            amount_eur="5.00",
            request_key="treasurer-once",
        )
        second = await refund_pledge(
            pledge_id,
            client,
            amount_eur="5.00",
            request_key="treasurer-once",
        )
        assert client.refund_n == 1
        expected = f"refund-{pledge_id}-treasurer-once"
        assert client.refund_keys == [expected]
        assert len(_normalize_refunds(second)) == 1
        assert first["refunds"][0]["id"] == second["refunds"][0]["id"]

    asyncio.run(run())


def test_two_same_amounts_different_request_keys(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="2.00", request_key="r1")
        await refund_pledge(pledge_id, client, amount_eur="2.00", request_key="r2")
        assert client.refund_n == 2
        assert len(_normalize_refunds(await get_ledger().get_pledge(pledge_id))) == 2
        assert refunded_amount_from_pledge(await get_ledger().get_pledge(pledge_id)) == pytest.approx(4.0)

    asyncio.run(run())


def test_two_same_amounts_without_key_second_is_409(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="2.00")
        assert client.refund_n == 1
        assert client.refund_keys[0] == f"refund-{pledge_id}-2.00"
        with pytest.raises(RefundRequestKeyRequired):
            await refund_pledge(pledge_id, client, amount_eur="2.00")
        assert client.refund_n == 1
        pledge = await get_ledger().get_pledge(pledge_id)
        assert len(_normalize_refunds(pledge)) == 1

    asyncio.run(run())


def test_two_partial_refunds_distinct_amounts_without_key(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="3.00")
        await refund_pledge(pledge_id, client, amount_eur="2.00")
        assert client.refund_n == 2
        pledge = await get_ledger().get_pledge(pledge_id)
        assert len(_normalize_refunds(pledge)) == 2

    asyncio.run(run())


def test_idempotency_key_header_dedupes_like_body_request_key(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers.escales import router, set_paypal_client_factory
    from tests.review_helpers import approve_capture_review

    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "c3-admin")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    reset_ledger()
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
                    "description": "header idem",
                    "milestone_id": "dep-mayotte",
                },
                headers={"PayPal-Request-Id": "c3-header-create"},
            )
            assert created.status_code == 200, created.text
            pledge_id = created.json()["id"]
            assert http.post(f"/api/escales/pledges/{pledge_id}/authorize").status_code == 200
            monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
            pledge_doc = asyncio.run(get_ledger().get_pledge(pledge_id))
            assert pledge_doc is not None
            pledge_doc["authorized_at"] = "2027-06-11T08:00:00+00:00"
            asyncio.run(get_ledger().save_pledge(pledge_doc))
            asyncio.run(approve_capture_review("dep-mayotte"))
            cap = http.post(
                f"/api/escales/pledges/{pledge_id}/capture",
                headers={"x-admin-key": "c3-admin"},
            )
            assert cap.status_code == 200, cap.text
            headers = {"x-admin-key": "c3-admin", "Idempotency-Key": "treasurer-hdr-once"}
            first = http.post(
                f"/api/escales/pledges/{pledge_id}/refund",
                headers=headers,
                json={"amount_eur": "4.00"},
            )
            second = http.post(
                f"/api/escales/pledges/{pledge_id}/refund",
                headers=headers,
                json={"amount_eur": "4.00", "request_key": "ignored-when-header-set"},
            )
            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            assert client_pp.refund_n == 1
            assert client_pp.refund_keys == [f"refund-{pledge_id}-treasurer-hdr-once"]
    finally:
        set_paypal_client_factory(None)
        reset_ledger()


def test_refund_above_remaining_raises_without_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="4.00")
        assert client.refund_n == 1
        with pytest.raises(ValueError, match="remaining refundable"):
            await refund_pledge(pledge_id, client, amount_eur="7.00")
        assert client.refund_n == 1

    asyncio.run(run())
