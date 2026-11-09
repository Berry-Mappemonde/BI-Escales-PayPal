"""Recover pledge authorization when PayPal returns ORDER_ALREADY_AUTHORIZED."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger, list_finance_entries
from app.escales.paypal_client import PayPalError
from app.escales.pledges import authorize_pledge, create_pledge, reset_ledger


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
    reset_ledger()

    async def seed():
        await get_ledger().ensure_milestone(
            "dep-la-rochelle",
            meta={
                "capture_on": "departure",
                "departure_iso": "2026-11-20T08:00:00+00:00",
            },
        )

    asyncio.run(seed())
    yield
    reset_ledger()


class RecoverSpy:
    def __init__(self, *, order_status: str = "APPROVED", get_order_body: dict | None = None):
        self.calls: list[tuple] = []
        self.n = 0
        self.order_status = order_status
        self.get_order_body = get_order_body
        self.authorize_raises: PayPalError | None = None

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
            }],
        }

    def authorize_order(self, order_id, **kwargs):
        self.calls.append(("authorize", order_id))
        if self.authorize_raises is not None:
            raise self.authorize_raises
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"AUTH-{order_id}",
                        "expiration_time": "2099-01-01T00:00:00Z",
                    }],
                },
            }],
        }

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        if self.get_order_body is not None:
            body = dict(self.get_order_body)
            body.setdefault("id", order_id)
            body.setdefault("status", self.order_status)
            return body
        return {"id": order_id, "status": self.order_status}


def _finance_authorized(pledge_id: str, entries: list[dict]) -> list[dict]:
    return [
        row for row in entries
        if row.get("kind") == "pledge_authorized" and row.get("pledge_id") == pledge_id
    ]


def test_order_already_authorized_recovers_pledge():
    async def body():
        spy = RecoverSpy(
            get_order_body={
                "purchase_units": [{
                    "payments": {
                        "authorizations": [{
                            "id": "28L87826KG020904R",
                            "status": "CREATED",
                            "expiration_time": "2099-06-01T00:00:00Z",
                        }],
                    },
                }],
            },
        )
        spy.authorize_raises = PayPalError(
            422,
            {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_AUTHORIZED"}]},
        )
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-1",
        )
        saved = await authorize_pledge(created["_id"], spy)
        assert saved["status"] == "authorized"
        assert saved["authorization_id"] == "28L87826KG020904R"
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 1
        assert ("authorize", created["order_id"]) in spy.calls
        assert ("orders.get", created["order_id"]) in spy.calls

    asyncio.run(body())


def test_repeat_authorize_is_noop_without_duplicate_finance():
    async def body():
        spy = RecoverSpy(
            get_order_body={
                "purchase_units": [{
                    "payments": {
                        "authorizations": [{
                            "id": "AUTH-RECOVER-NOOP",
                            "status": "PENDING",
                            "expiration_time": "2099-06-01T00:00:00Z",
                        }],
                    },
                }],
            },
        )
        spy.authorize_raises = PayPalError(
            422,
            {"details": [{"issue": "ORDER_ALREADY_AUTHORIZED"}]},
        )
        created = await create_pledge(
            amount_eur="15.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-2",
        )
        first = await authorize_pledge(created["_id"], spy)
        calls_after_first = len(spy.calls)
        second = await authorize_pledge(created["_id"], spy)
        assert second["status"] == "authorized"
        assert second["authorization_id"] == first["authorization_id"]
        assert len(spy.calls) == calls_after_first
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 1

    asyncio.run(body())


def test_other_422_issue_still_raises():
    async def body():
        spy = RecoverSpy()
        spy.authorize_raises = PayPalError(
            422,
            {"details": [{"issue": "INSTRUMENT_DECLINED"}]},
        )
        created = await create_pledge(
            amount_eur="10.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-3",
        )
        with pytest.raises(PayPalError) as caught:
            await authorize_pledge(created["_id"], spy)
        assert caught.value.status == 422
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored is not None
        assert stored["status"] == "created"
        entries = await list_finance_entries()
        assert _finance_authorized(created["_id"], entries) == []

    asyncio.run(body())


def test_order_already_authorized_without_usable_auth_still_raises():
    async def body():
        spy = RecoverSpy(
            get_order_body={
                "purchase_units": [{
                    "payments": {
                        "authorizations": [{
                            "id": "VOIDED-ONLY",
                            "status": "VOIDED",
                        }],
                    },
                }],
            },
        )
        original = PayPalError(
            422,
            {"details": [{"issue": "ORDER_ALREADY_AUTHORIZED"}]},
        )
        spy.authorize_raises = original
        created = await create_pledge(
            amount_eur="12.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-4",
        )
        with pytest.raises(PayPalError) as caught:
            await authorize_pledge(created["_id"], spy)
        assert caught.value is original or caught.value.status == 422
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored is not None
        assert stored["status"] == "created"

    asyncio.run(body())
