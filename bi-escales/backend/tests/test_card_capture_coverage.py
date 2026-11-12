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
    ("N", "", "NO", False), ("U", "", "NO", False), ("B", "", "NO", False),
    ("Y", "N", "NO", False), ("Y", "R", "NO", False), ("Y", "C", "UNKNOWN", False),
    ("Y", "U", "UNKNOWN", False), ("Y", "", "NO", False), ("", "", "", True),
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


@pytest.mark.parametrize("auth,allowed", [(None,True),({},True),({"liability_shift":"UNKNOWN"},True),({"liability_shift":"NO","three_d_secure":{"enrollment_status":"Y","authentication_status":"N"}},False)])
def test_approved_card_without_a_3ds_attempt_is_accepted(auth,allowed):
    from app.escales.pledges import _require_card_capture_approval
    card={"last_digits":"9038","brand":"VISA"}
    if auth is not None:card['authentication_result']=auth
    order={"id":"CARD","status":"APPROVED","payment_source":{"card":card}}
    if allowed:_require_card_capture_approval(order)
    else:
        with pytest.raises(ValueError):_require_card_capture_approval(order)


def test_pending_card_capture_reconciles_existing_capture_and_serializes_double_click(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    class CardSpy(Spy):
        def get_card_order(self, order_id):
            return {"id": order_id, "status": "APPROVED", "payment_source": {
                "card": {"brand": "VISA", "last_digits": "1111", "authentication_result": {"liability_shift": "POSSIBLE", "three_d_secure": {"enrollment_status": "Y", "authentication_status": "Y"}}}}}

        def capture_order(self, order_id, **kwargs):
            self.calls.append(("orders.capture", order_id))
            return {"id": order_id, "purchase_units": [{"payments": {"captures": [
                {"id": "CAP-P", "status": "PENDING"}]}}]}

        def get_capture(self, capture_id):
            return {"id": capture_id, "status": self.capture_status}

    async def run():
        reset_ledger()
        spy = CardSpy()
        spy.capture_status = "PENDING"
        created = await create_pledge(amount_eur="10.00", description="Pending card", milestone_id="",
            kind="project_pledge", checkout_method="card", client=spy)
        results = await asyncio.gather(*[authorize_pledge(created["_id"], spy) for _ in range(2)])
        assert [r["status"] for r in results] == ["pending", "pending"]
        spy.capture_status = "COMPLETED"
        assert (await authorize_pledge(created["_id"], spy))["status"] == "captured"
        assert (await authorize_pledge(created["_id"], spy))["status"] == "captured"
        assert len([c for c in spy.calls if c[0] == "orders.capture"]) == 1
    asyncio.run(run())


@pytest.mark.parametrize("sdk_enabled", [False, True])
def test_pending_capture_read_uses_the_selected_transport(monkeypatch, sdk_enabled):
    from app.escales.paypal_sdk_gateway import reset_client
    from tests import test_paypal_sdk_money_path as wire
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", str(int(sdk_enabled)))
    original = wire._dispatch
    def dispatch(method, path):
        if path == "/v2/payments/captures/CAP-P":
            return 200, {"id": "CAP-P", "status": "PENDING", "amount": {"value": "10.00", "currency_code": "EUR"}}
        return original(method, path)
    monkeypatch.setattr(wire, "_dispatch", dispatch)
    records = []
    reset_client()
    if sdk_enabled:
        wire._install(records)
    def handle(request):
        assert not sdk_enabled, "SDK path fell back to httpx"
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test", "expires_in": 300})
        records.append({"path": request.url.path})
        return httpx.Response(200, json={"id": "CAP-P", "status": "PENDING"})
    try:
        client = PayPalClient(EscalesConfig("test-client-id", "test-secret"), transport=httpx.MockTransport(handle))
        assert client.get_capture("CAP-P")["status"] == "PENDING"
        assert any(r["path"] == "/v2/payments/captures/CAP-P" for r in records)
    finally:
        reset_client()
