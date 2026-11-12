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


def test_common_fund_card_uses_capture_with_card_source(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "0")
    import json
    import httpx
    from app.escales.config import EscalesConfig
    from app.escales.paypal_client import PayPalClient
    bodies = []
    def handler(request):
        if request.url.path.endswith('/oauth2/token'):
            return httpx.Response(200, json={"access_token": "test", "expires_in": 300})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "CARD-FUND", "status": "CREATED"})
    client = PayPalClient(EscalesConfig("id", "secret"), transport=httpx.MockTransport(handler))
    async def run():
        reset_ledger()
        row = await create_pledge(amount_eur="10.00", description="Common fund", milestone_id="",
            kind="common_fund", checkout_method="card", client=client)
        assert row["kind"] == "common_fund" and row["payment_mode"] == "CAPTURE"
    asyncio.run(run())
    assert bodies[0]["intent"] == "CAPTURE"
    assert bodies[0]["payment_source"]["card"]["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"
