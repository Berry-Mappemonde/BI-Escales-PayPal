"""Marina payout batch webhook updates pledge status."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger, record_finance, reset_ledger
from app.escales.marina_berth_settlement import apply_payout_batch_webhook


def test_payout_batch_webhook_updates_pledge():
    reset_ledger()

    async def body():
        pledge = await get_ledger().insert_pledge_once(
            {
                "_id": "p-marina-1",
                "status": "captured",
                "kind": "berth",
                "amount_eur": "30.00",
                "marina_payout_batch_id": "BATCH-9",
                "history": ["captured"],
            }
        )
        await record_finance(
            "marina_payout_sent",
            pledge_id=pledge["_id"],
            payout_batch_id="BATCH-9",
            amount_eur="27.00",
            status="pending",
        )
        await apply_payout_batch_webhook(
            batch_id="BATCH-9",
            event_type="PAYMENT.PAYOUTSBATCH.SUCCESS",
            batch_status="SUCCESS",
        )
        saved = await get_ledger().get_pledge("p-marina-1")
        assert saved["marina_payout_status"] == "success"

    asyncio.run(body())
    reset_ledger()
