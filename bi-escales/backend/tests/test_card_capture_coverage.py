"""Cards use CAPTURE + SCA for immediate donations, not AUTHORIZE."""
import asyncio
import json
import httpx
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient
from app.escales.payment_mode import preview_payment_mode
from app.escales.pledges import create_pledge
from app.escales.ledger import reset_ledger


def test_card_project_capture_request_and_preview(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "0")
    requests = []
    def handler(request):
        if request.url.path.endswith('/oauth2/token'):
            return httpx.Response(200, json={"access_token": "test", "expires_in": 300})
        requests.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ORDER-CARD", "status": "CREATED"})
    client = PayPalClient(EscalesConfig("test-client", "test-secret"), transport=httpx.MockTransport(handler))
    async def run():
        reset_ledger()
        assert await preview_payment_mode("", "project_pledge") == "CAPTURE"
        row = await create_pledge(amount_eur="10.00", description="Project", milestone_id="",
            kind="project_pledge", target_id="projet-ecole", checkout_method="card", client=client)
        assert row["payment_mode"] == "CAPTURE"
        assert row["checkout_method"] == "card"
    asyncio.run(run())
    assert requests[0]["intent"] == "CAPTURE"
    assert "paypal" not in requests[0]["payment_source"]
    assert requests[0]["payment_source"]["card"]["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"
