"""Orphan PayPal simulator webhooks: accepted but no local subscription, vault, or dispute rows."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger, list_finance_entries
from app.escales.paypal_disputes import list_dispute_snapshots
from app.escales.paypal_subscriptions import list_subscriptions_local
from app.escales.pledges import reset_ledger
from app.escales.webhooks import verify_and_process


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-DEMO")
    reset_ledger()
    yield
    reset_ledger()


class WSpy:
    def verify_webhook_signature(self, **kwargs):
        assert kwargs["webhook_id"] == "WH-DEMO"
        return {"verification_status": "SUCCESS"}


def _headers(transmission_id: str) -> dict:
    return {
        "PAYPAL-TRANSMISSION-ID": transmission_id,
        "PAYPAL-TRANSMISSION-TIME": "2026-11-04T12:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    }


async def _post_event(event: dict, transmission_id: str) -> dict:
    return await verify_and_process(
        raw_body=json.dumps(event).encode(),
        headers=_headers(transmission_id),
        client=WSpy(),
    )


def test_orphan_dispute_webhook_does_not_create_dispute_snapshot():
    async def run():
        result = await _post_event(
            {
                "id": "evt-sim-dispute",
                "event_type": "CUSTOMER.DISPUTE.CREATED",
                "resource": {"dispute_id": "PP-SIM-DISPUTE", "status": "OPEN"},
            },
            "tx-sim-dispute",
        )
        assert result["accepted"] is True
        assert result.get("pledge_id") is None
        snapshots = await list_dispute_snapshots()
        assert snapshots == []
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert "paypal_dispute_snapshot" not in kinds
        assert kinds.count("webhook_received") == 1

    asyncio.run(run())


def test_orphan_vault_token_webhooks_do_not_touch_pledges():
    async def run():
        created = await _post_event(
            {
                "id": "evt-sim-vault-created",
                "event_type": "VAULT.PAYMENT-TOKEN.CREATED",
                "resource": {"id": "VT-SIM-TOKEN", "status": "CREATED"},
            },
            "tx-sim-vault-created",
        )
        assert created["accepted"] is True
        deleted = await _post_event(
            {
                "id": "evt-sim-vault-deleted",
                "event_type": "VAULT.PAYMENT-TOKEN.DELETED",
                "resource": {"id": "VT-SIM-TOKEN", "status": "DELETED"},
            },
            "tx-sim-vault-deleted",
        )
        assert deleted["accepted"] is True
        pledges = await get_ledger().list_pledges()
        assert pledges == []
        for row in pledges:
            assert not row.get("vault_id")
            assert row.get("vault_token_deleted") is not True

    asyncio.run(run())


def test_orphan_subscription_webhooks_do_not_create_local_subscription_rows():
    async def run():
        await _post_event(
            {
                "id": "evt-sim-sub-act",
                "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
                "resource": {"id": "I-SIM-SUB", "plan_id": "P-SIM", "status": "ACTIVE"},
            },
            "tx-sim-sub-act",
        )
        await _post_event(
            {
                "id": "evt-sim-sub-cancel",
                "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
                "resource": {"id": "I-SIM-SUB", "plan_id": "P-SIM", "status": "CANCELLED"},
            },
            "tx-sim-sub-cancel",
        )
        assert await list_subscriptions_local() == []
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert "paypal_subscription_local" not in kinds

    asyncio.run(run())


def test_orphan_capture_webhook_does_not_create_pledge_or_capture_finance():
    async def run():
        result = await _post_event(
            {
                "id": "evt-sim-cap",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {
                    "id": "CAP-SIM-SAMPLE",
                    "status": "COMPLETED",
                    "links": [{
                        "href": "https://api.sandbox.paypal.com/v2/payments/captures/CAP-SIM-SAMPLE",
                        "rel": "self",
                    }],
                },
            },
            "tx-sim-cap",
        )
        assert result["accepted"] is True
        assert result.get("pledge_id") is None
        assert await get_ledger().list_pledges() == []
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert "pledge_captured" not in kinds

    asyncio.run(run())
