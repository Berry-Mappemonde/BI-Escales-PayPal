"""Append-only finance ledger aligned with the audit journal."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import COLLECTIONS, FINANCE_COLLECTION, list_finance_entries
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, reset_ledger, void_pledge


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


class Spy:
    def __init__(self):
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2099-01-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        return {"status": "COMPLETED"}

    def void_authorization(self, authorization_id, **kwargs):
        return {}


def test_finance_collection_is_namespaced():
    assert FINANCE_COLLECTION in COLLECTIONS
    assert "escales_webhooks" in COLLECTIONS


def test_finance_tracks_pledge_lifecycle(monkeypatch):
    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="fin-1",
        )
        await authorize_pledge(created["_id"], spy)
        other = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="fin-2",
        )
        await authorize_pledge(other["_id"], spy)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
        await capture_pledge(created["_id"], spy)
        await void_pledge(other["_id"], spy)
        entries = await list_finance_entries()
        kinds = [entry["kind"] for entry in entries]
        assert kinds.count("pledge_created") == 2
        assert kinds.count("pledge_authorized") == 2
        assert kinds.count("pledge_captured") == 1
        assert kinds.count("pledge_voided") == 1
        assert all(entry["collection"] == FINANCE_COLLECTION for entry in entries)
        captured = next(entry for entry in entries if entry["kind"] == "pledge_captured")
        assert captured["pledge_id"] == created["_id"]
        assert captured["actor"] == "treasurer"
        assert captured["pledge_kind"] == "mile"
        assert captured["target_id"] == "dzaoudzi-mayotte"

    asyncio.run(body())
