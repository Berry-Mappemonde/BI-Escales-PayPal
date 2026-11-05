"""Webhook void syncs pledge status for treasurer admin."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import authorize_pledge, create_pledge, reset_ledger
from app.escales.webhooks import _apply_event


class Spy:
    def create_authorize_order(self, **kwargs):
        return {"id": "ORD-V", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/x"}]}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def authorize_order(self, order_id, *, pledge_id=None):
        return {
            "id": order_id,
            "purchase_units": [
                {"payments": {"authorizations": [{"id": "AUTH1", "expiration_time": "2099-01-01T00:00:00Z"}]}}
            ],
        }


def test_authorization_voided_webhook_marks_pledge_voided(monkeypatch):
    reset_ledger()

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="5.00",
            description="5 miles",
            milestone_id="dep-mayotte",
            client=spy,
        )
        await authorize_pledge(created["_id"], spy)
        event = {
            "event_type": "PAYMENT.AUTHORIZATION.VOIDED",
            "resource": {
                "id": "AUTH1",
                "supplementary_data": {"related_ids": {"order_id": "ORD-V"}},
            },
        }
        result = await _apply_event(event)
        assert result.get("pledge_id") == created["_id"]
        from app.escales.ledger import get_ledger

        reloaded = await get_ledger().get_pledge(created["_id"])
        assert reloaded["status"] == "voided"
        assert "webhook_authorization_voided" in reloaded.get("history", [])

    asyncio.run(body())
    reset_ledger()
