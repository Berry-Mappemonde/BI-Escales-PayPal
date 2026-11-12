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


import pytest
from app.escales.pledges import authorize_pledge, require_pledge
from tests.test_escales_pledges import Spy


@pytest.mark.parametrize("enrollment,authentication,shift,allowed", [
    ("Y", "Y", "POSSIBLE", True), ("Y", "A", "POSSIBLE", True),
    ("N", "", "NO", True), ("U", "", "NO", True), ("B", "", "NO", True),
    ("Y", "N", "NO", False), ("Y", "R", "NO", False), ("Y", "C", "UNKNOWN", False),
    ("Y", "U", "UNKNOWN", False), ("Y", "", "NO", False), ("", "", "", False),
])
def test_3ds_is_checked_before_card_capture(monkeypatch, enrollment, authentication, shift, allowed):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    class CardSpy(Spy):
        def get_order(self, order_id):
            return {"id": order_id, "status": "APPROVED", "payment_source": {"card": {
                "authentication_result": {"liability_shift": shift,
                    "three_d_secure": {"enrollment_status": enrollment, "authentication_status": authentication}}}}}
    async def run():
        reset_ledger()
        client = CardSpy()
        pledge = await create_pledge(amount_eur="10.00", description="Card donation", milestone_id="",
            kind="project_pledge", target_id="projet-ecole", checkout_method="card", client=client)
        if allowed:
            paid = await authorize_pledge(pledge["_id"], client)
            assert paid["status"] == "captured"
            assert any(c[0] == "orders.capture" for c in client.calls)
        else:
            with pytest.raises(ValueError, match="authentication"):
                await authorize_pledge(pledge["_id"], client)
            assert not any(c[0] == "orders.capture" for c in client.calls)
            assert (await require_pledge(pledge["_id"]))["status"] == "created"
    asyncio.run(run())


def test_card_create_approval_and_capture_use_the_generated_sdk(monkeypatch):
    from tests import test_paypal_sdk_money_path as wire
    from app.escales.paypal_sdk_gateway import reset_client
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")
    original = wire._dispatch
    def dispatch(method, path):
        if path == "/v2/checkout/orders":
            return 201, {"id": "CARD-DON", "status": "CREATED", "intent": "CAPTURE"}
        if path == "/v2/checkout/orders/CARD-DON":
            return 200, {"id": "CARD-DON", "status": "APPROVED", "payment_source": {"card": {
                "authentication_result": {"liability_shift": "POSSIBLE", "three_d_secure": {
                    "enrollment_status": "Y", "authentication_status": "Y"}}}}}
        if path == "/v2/checkout/orders/CARD-DON/capture":
            return 201, {"id": "CARD-DON", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{
                "id": "CAP-DON", "status": "COMPLETED", "amount": {"currency_code": "EUR", "value": "10.00"}}]}}]}
        return original(method, path)
    monkeypatch.setattr(wire, "_dispatch", dispatch)
    reset_client(); records = []; wire._install(records)
    def forbid(request): raise AssertionError("Card path must not use httpx with SDK enabled")
    client = PayPalClient(EscalesConfig("test-client-id", "test-secret"), transport=httpx.MockTransport(forbid))
    async def run():
        reset_ledger()
        created = await create_pledge(amount_eur="10.00", description="Card donation", milestone_id="",
            kind="project_pledge", target_id="projet-ecole", checkout_method="card", client=client)
        paid = await authorize_pledge(created["_id"], client)
        assert paid["status"] == "captured"
    try:
        asyncio.run(run())
        assert [r["path"] for r in wire._operations(records)] == [
            "/v2/checkout/orders", "/v2/checkout/orders/CARD-DON",
            "/v2/checkout/orders/CARD-DON", "/v2/checkout/orders/CARD-DON/capture"]
    finally:
        reset_client(); reset_ledger()


def test_card_approval_read_requests_authentication_fields(monkeypatch):
    import httpx
    import requests
    from urllib.parse import urlparse, parse_qs
    from app.escales.config import EscalesConfig
    from app.escales.paypal_client import PayPalClient
    from app.escales.paypal_sdk_gateway import reset_client
    from tests import test_paypal_sdk_money_path as wire
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")
    reset_client()
    seen = []
    original = wire._Router.send
    def checked(self, request, **kwargs):
        if urlparse(request.url).path == "/v2/checkout/orders/ORDER-CAP":
            seen.append(parse_qs(urlparse(request.url).query))
        return original(self, request, **kwargs)
    monkeypatch.setattr(wire._Router, "send", checked)
    wire._install([])
    try:
        client = PayPalClient(EscalesConfig("test-client-id", "test-secret"), transport=httpx.MockTransport(lambda r: pytest.fail("no httpx")))
        client.get_card_order("ORDER-CAP")
        assert seen == [{}, {"fields": ["payment_source"]}]
    finally:
        reset_client()


def test_card_read_keeps_state_when_projection_omits_status(monkeypatch):
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "0")
    def handler(request):
        if request.url.path.endswith('/oauth2/token'):
            return httpx.Response(200, json={"access_token":"test", "expires_in":300})
        if request.url.params.get('fields') == 'payment_source':
            return httpx.Response(200, json={"id":"CARD", "payment_source":{"card":{"authentication_result":{
                "liability_shift":"POSSIBLE", "three_d_secure":{"enrollment_status":"Y", "authentication_status":"Y"}}}}})
        return httpx.Response(200, json={"id":"CARD", "status":"APPROVED"})
    client=PayPalClient(EscalesConfig("test-client", "test-secret"), transport=httpx.MockTransport(handler))
    from app.escales.pledges import _require_card_capture_approval
    order=client.get_card_order("CARD")
    assert order['status']=='APPROVED'
    _require_card_capture_approval(order)
