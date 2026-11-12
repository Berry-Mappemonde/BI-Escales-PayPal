"""Judge-path SDK calls: reauthorize, card setup token, delete payment token.

Flag off stays on httpx. Flag on uses the generated SDK and keeps the card
setup JSON the generated card model would drop. Mock and, for delete, the
request id are attached on the way out because SDK 2.4.0 cannot set them.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter

from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient
from app.escales.paypal_sdk_gateway import build_sandbox_client, install_client, reset_client
from paypalserversdk.http.http_call_back import HttpCallBack

TOKEN = {"access_token": "tok", "expires_in": 3200, "token_type": "Bearer"}
MOCK = '{"mock_application_codes":"INSTRUMENT_DECLINED"}'


class _Catcher(HttpCallBack):
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def on_before_request(self, request: Any) -> None:
        self.requests.append(request)

    def on_after_response(self, response: Any) -> None:
        return None


def _payload(method: str, path: str) -> tuple[int, Any]:
    if path == "/v1/oauth2/token":
        return 200, TOKEN
    if method == "POST" and path == "/v2/payments/authorizations/AUTH-1/reauthorize":
        return 200, {"id": "AUTH-1", "status": "CREATED"}
    if method == "POST" and path == "/v3/vault/setup-tokens":
        return 201, {"id": "SETUP-CARD", "status": "PAYER_ACTION_REQUIRED"}
    if method == "DELETE" and path == "/v3/vault/payment-tokens/VAULT-1":
        return 204, None
    return 500, {"name": "UNEXPECTED", "message": f"{method} {path}"}


def _json_body(raw: Any) -> Any:
    if raw in (None, b"", ""):
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    text = str(raw).strip()
    if not text or text[0] not in "{[":
        return None
    return json.loads(text)


class _Router(HTTPAdapter):
    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        path = urlparse(request.url or "").path
        method = (request.method or "").upper()
        status, payload = _payload(method, path)
        response = requests.Response()
        response.status_code = status
        response.reason = "OK" if status < 400 else "Error"
        response.url = request.url or ""
        response.headers["Content-Type"] = "application/json"
        response._content = b"" if payload is None else json.dumps(payload).encode()
        response.request = request
        return response


@pytest.fixture(autouse=True)
def _reset() -> Any:
    reset_client()
    yield
    reset_client()


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)


def _httpx_client() -> PayPalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, payload = _payload(request.method.upper(), request.url.path)
        if payload is None:
            return httpx.Response(status, headers={"Content-Type": "application/json"})
        return httpx.Response(status, json=payload)

    client = PayPalClient(
        EscalesConfig("test-client-id", "test-secret"),
        transport=httpx.MockTransport(handler),
    )
    client.mock_response = MOCK
    return client


def _sdk_client() -> tuple[PayPalClient, _Catcher]:
    catcher = _Catcher()
    session = requests.Session()
    session.mount("https://", _Router())
    session.mount("http://", _Router())
    install_client(build_sandbox_client(http_client_instance=session, http_call_back=catcher))
    client = PayPalClient(EscalesConfig("test-client-id", "test-secret"))
    client.mock_response = MOCK
    return client, catcher


def _seen(catcher: _Catcher, method: str, path: str) -> Any:
    matches = []
    for request in catcher.requests:
        if urlparse(request.query_url).path == path and str(request.http_method).upper().endswith(method):
            matches.append(request)
    assert len(matches) == 1
    return matches[0]


def _header(request: Any, name: str) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    for key, value in dict(headers).items():
        if str(key).lower() == name.lower() and value not in (None, ""):
            return str(value)
    return None


def test_flag_off_keeps_httpx_for_the_three_calls(sandbox: None) -> None:
    client = _httpx_client()
    seen: list[httpx.Request] = []
    original = client._http.request

    def spy(method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = original(method, url, **kwargs)
        seen.append(response.request)
        return response

    client._http.request = spy  # type: ignore[method-assign]
    assert client.reauthorize("AUTH-1", pledge_id="pledge-1")["status"] == "CREATED"
    setup = client.create_card_setup_token(
        "https://example.test/return",
        "https://example.test/cancel",
        customer_id="cust-1",
    )
    assert setup["id"] == "SETUP-CARD"
    assert client.delete_payment_token("VAULT-1") == {}
    by_path = {request.url.path: request for request in seen}
    reauthorize = by_path["/v2/payments/authorizations/AUTH-1/reauthorize"]
    assert reauthorize.method == "POST"
    assert reauthorize.headers["PayPal-Request-Id"] == "reauthorize-pledge-1"
    assert reauthorize.headers["Prefer"] == "return=representation"
    assert reauthorize.headers["PayPal-Mock-Response"] == MOCK
    assert json.loads(reauthorize.content) == {}
    card = by_path["/v3/vault/setup-tokens"]
    body = json.loads(card.content)
    assert body["payment_source"]["card"]["usage_type"] == "MERCHANT"
    assert body["payment_source"]["card"]["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"
    assert card.headers["PayPal-Request-Id"] == "card-setup-token-cust-1"
    deleted = by_path["/v3/vault/payment-tokens/VAULT-1"]
    assert deleted.method == "DELETE"
    assert "PayPal-Request-Id" not in deleted.headers


def test_sdk_reauthorize_card_setup_and_delete_keep_wire_shape(
    sandbox: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "true")
    client, catcher = _sdk_client()
    assert client.reauthorize("AUTH-1", pledge_id="pledge-1")["id"] == "AUTH-1"
    setup = client.create_card_setup_token(
        "https://example.test/return",
        "https://example.test/cancel",
        customer_id="cust-1",
    )
    assert setup["id"] == "SETUP-CARD"
    assert client.delete_payment_token("VAULT-1") == {}

    reauthorize = _seen(catcher, "POST", "/v2/payments/authorizations/AUTH-1/reauthorize")
    assert _header(reauthorize, "PayPal-Request-Id") == "reauthorize-pledge-1"
    assert _header(reauthorize, "Prefer") == "return=representation"
    assert _header(reauthorize, "PayPal-Mock-Response") == MOCK
    assert _json_body(reauthorize.parameters) == {}

    card = _seen(catcher, "POST", "/v3/vault/setup-tokens")
    body = _json_body(card.parameters)
    assert body["customer"]["id"] == "cust-1"
    assert body["payment_source"]["card"]["usage_type"] == "MERCHANT"
    assert body["payment_source"]["card"]["usage_pattern"] == "UNSCHEDULED_POSTPAID"
    assert body["payment_source"]["card"]["permit_multiple_payment_tokens"] is False
    assert body["payment_source"]["card"]["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"
    assert _header(card, "PayPal-Request-Id") == "card-setup-token-cust-1"
    assert _header(card, "PayPal-Mock-Response") == MOCK

    deleted = _seen(catcher, "DELETE", "/v3/vault/payment-tokens/VAULT-1")
    assert _header(deleted, "PayPal-Request-Id") == "delete-payment-token-VAULT-1"
    assert _header(deleted, "PayPal-Mock-Response") == MOCK

    oauth = _seen(catcher, "POST", "/v1/oauth2/token")
    assert _header(oauth, "PayPal-Mock-Response") is None
    assert _header(oauth, "PayPal-Request-Id") is None
