"""PAY-03: common fund approval captures immediately, once, without review."""
import asyncio

from app.escales.ledger import reset_ledger, list_finance_entries
from app.escales.payment_mode import preview_payment_mode
from app.escales.pledges import create_pledge, authorize_pledge
from tests.test_escales_pledges import Spy


def test_common_fund_immediate_capture_and_concurrent_approval(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    async def run():
        reset_ledger()
        spy = Spy()
        assert await preview_payment_mode("", "common_fund") == "CAPTURE"
        pledge = await create_pledge(amount_eur="10.00", description="Common fund",
            milestone_id="", client=spy, kind="common_fund", client_key="fund-once")
        assert pledge["kind"] == "common_fund"
        assert pledge["target_id"] == "fonds-commun"
        assert pledge["intent"] == pledge["payment_mode"] == "CAPTURE"
        receipts = await asyncio.gather(*(authorize_pledge(pledge["_id"], spy) for _ in range(3)))
        assert all(row["status"] == "captured" for row in receipts)
        assert sum(call[0] == "orders.capture" for call in spy.calls) == 1
        assert sum(e["kind"] == "pledge_captured" for e in await list_finance_entries()) == 1
    asyncio.run(run())
