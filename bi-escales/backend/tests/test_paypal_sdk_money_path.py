"""APIM-3 write path: SDK at the HTTP boundary versus the httpx client.

Flag off never imports or calls the SDK. Flag on keeps the same ledger rows,
finance rows, and PayPal status codes. The stub sits under ``requests``, so the
SDK still serializes the body and maps errors.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter

from app.escales.audit import list_entries
from app.escales.config import EscalesConfig
from app.escales.ledger import get_ledger, list_finance_entries, reset_ledger
from app.escales.paypal_client import PayPalClient, PayPalError, paypal_error_issues
from app.escales.paypal_sdk_gateway import build_sandbox_client, install_client, reset_client
from app.escales.paypal_subscriptions import create_crew_subscription
from app.escales.pledges import (
    _create_vault_pledge,
    authorize_pledge,
    capture_pledge,
    refund_pledge,
    register_vault_pledge,
    void_pledge,
)
from paypalserversdk.http.http_call_back import HttpCallBack

BACKEND = Path(__file__).resolve().parents[1]
FIXED_AT = "2026-11-12T12:00:00+00:00"
TOKEN = {"access_token": "tok", "expires_in": 3200, "token_type": "Bearer"}

AUTH_ORDER = {
    "id": "ORDER-AUTH",
    "intent": "AUTHORIZE",
    "status": "COMPLETED",
    "purchase_units": [{
        "reference_id": "pledge-auth",
        "custom_id": "pledge-auth",
        "invoice_id": "pledge-auth",
        "amount": {"currency_code": "EUR", "value": "20.00"},
        "payments": {"authorizations": [{
            "id": "AUTH-1",
            "status": "CREATED",
            "amount": {"currency_code": "EUR", "value": "20.00"},
            "expiration_time": "2026-12-11T08:00:00Z",
        }]},
    }],
}
APPROVED_ORDER = {
    "id": "ORDER-AUTH",
    "intent": "AUTHORIZE",
    "status": "APPROVED",
    "purchase_units": [{
        "reference_id": "pledge-auth",
        "custom_id": "pledge-auth",
        "invoice_id": "pledge-auth",
        "amount": {"currency_code": "EUR", "value": "20.00"},
    }],
}
CAPTURED = {
    "id": "CAP-AUTH",
    "status": "COMPLETED",
    "final_capture": True,
    "disbursement_mode": "INSTANT",
    "amount": {"currency_code": "EUR", "value": "20.00"},
    "seller_receivable_breakdown": {
        "gross_amount": {"currency_code": "EUR", "value": "20.00"},
        "paypal_fee": {"currency_code": "EUR", "value": "0.87"},
        "net_amount": {"currency_code": "EUR", "value": "19.13"},
    },
}
REFUND = {
    "id": "REF-1",
    "status": "COMPLETED",
    "amount": {"currency_code": "EUR", "value": "20.00"},
    "seller_payable_breakdown": {
        "gross_amount": {"currency_code": "EUR", "value": "20.00"},
        "paypal_fee": {"currency_code": "EUR", "value": "0.87"},
        "net_amount": {"currency_code": "EUR", "value": "19.13"},
    },
}
VOIDED = {"id": "VOID-1", "status": "VOIDED"}
ORDER_CAPTURE = {
    "id": "ORDER-CAP",
    "intent": "CAPTURE",
    "status": "COMPLETED",
    "purchase_units": [{
        "reference_id": "pledge-cap",
        "payments": {"captures": [{
            "id": "CAP-ORDER",
            "status": "COMPLETED",
            "final_capture": True,
            "disbursement_mode": "INSTANT",
            "amount": {"currency_code": "EUR", "value": "15.00"},
            "seller_receivable_breakdown": {
                "gross_amount": {"currency_code": "EUR", "value": "15.00"},
                "paypal_fee": {"currency_code": "EUR", "value": "0.75"},
                "net_amount": {"currency_code": "EUR", "value": "14.25"},
            },
        }]},
    }],
}
APPROVED_CAPTURE_ORDER = {
    "id": "ORDER-CAP",
    "intent": "CAPTURE",
    "status": "APPROVED",
    "purchase_units": [{
        "reference_id": "pledge-cap",
        "amount": {"currency_code": "EUR", "value": "15.00"},
    }],
}
RECOVER_ORDER = {
    "id": "ORDER-RECOVER",
    "intent": "AUTHORIZE",
    "status": "COMPLETED",
    "purchase_units": [{
        "reference_id": "pledge-recover",
        "custom_id": "pledge-recover",
        "invoice_id": "pledge-recover",
        "amount": {"currency_code": "EUR", "value": "20.00"},
        "payments": {"authorizations": [{
            "id": "AUTH-R",
            "status": "CREATED",
            "amount": {"currency_code": "EUR", "value": "20.00"},
            "expiration_time": "2026-12-11T08:00:00Z",
        }]},
    }],
}
ALREADY = {
    "name": "UNPROCESSABLE_ENTITY",
    "message": "already authorized",
    "debug_id": "dbg-recover",
    "details": [{"issue": "ORDER_ALREADY_AUTHORIZED", "description": "already authorized"}],
}
DECLINED = {
    "name": "UNPROCESSABLE_ENTITY",
    "message": "declined",
    "debug_id": "dbg-declined",
    "details": [{"issue": "INSTRUMENT_DECLINED", "description": "declined"}],
}
SETUP = {
    "id": "SETUP1",
    "status": "CREATED",
    "customer": {"id": "cust-1"},
    "links": [{
        "href": "https://www.sandbox.paypal.com/agreements/approve?approval_session_id=SETUP1",
        "rel": "approve",
        "method": "GET",
    }],
}
SETUP_APPROVED = {
    "id": "SETUP1",
    "status": "APPROVED",
    "customer": {"id": "cust-1"},
}
PAYMENT_TOKEN = {
    "id": "VAULT1",
    "payment_source": {"paypal": {"usage_type": "MERCHANT", "permit_multiple_payment_tokens": False}},
}
SUBSCRIPTION = {
    "id": "I-SUB1",
    "plan_id": "P-EN",
    "status": "APPROVAL_PENDING",
    "links": [{
        "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1",
        "rel": "approve",
        "method": "GET",
    }],
}


_REAL_UUID4 = uuid.uuid4


class _Ids:
    """Stable ids for ledger rows. SDK internals keep the real generator."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> uuid.UUID:
        for frame in traceback.extract_stack():
            name = frame.filename.replace("\\", "/")
            if "paypalserversdk" in name or "apimatic" in name:
                return _REAL_UUID4()
        self.n += 1
        return uuid.UUID(int=self.n)


class ResponseCatcher(HttpCallBack):
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def on_before_request(self, request: Any) -> None:
        self.requests.append(request)

    def on_after_response(self, response: Any) -> None:
        return None


def _dispatch(method: str, path: str) -> tuple[int, Any]:
    if path == "/v1/oauth2/token":
        return 200, TOKEN
    if method == "GET" and path == "/v2/checkout/orders/ORDER-AUTH":
        return 200, APPROVED_ORDER
    if method == "POST" and path == "/v2/checkout/orders/ORDER-AUTH/authorize":
        return 200, AUTH_ORDER
    if method == "POST" and path == "/v2/payments/authorizations/AUTH-1/capture":
        return 200, CAPTURED
    if method == "POST" and path == "/v2/payments/captures/CAP-AUTH/refund":
        return 200, REFUND
    if method == "POST" and path == "/v2/payments/authorizations/AUTH-VOID/void":
        return 200, VOIDED
    if method == "GET" and path == "/v2/checkout/orders/ORDER-CAP":
        return 200, APPROVED_CAPTURE_ORDER
    if method == "POST" and path == "/v2/checkout/orders/ORDER-CAP/capture":
        return 200, ORDER_CAPTURE
    if method == "GET" and path == "/v2/checkout/orders/ORDER-RECOVER":
        return 200, RECOVER_ORDER
    if method == "GET" and path == "/v2/checkout/orders/ORDER-DECLINED":
        approved = dict(APPROVED_ORDER)
        approved["id"] = "ORDER-DECLINED"
        return 200, approved
    if method == "POST" and path == "/v2/checkout/orders/ORDER-RECOVER/authorize":
        return 422, ALREADY
    if method == "POST" and path == "/v2/checkout/orders/ORDER-DECLINED/authorize":
        return 422, DECLINED
    if method == "POST" and path == "/v3/vault/setup-tokens":
        return 200, SETUP
    if method == "GET" and path == "/v3/vault/setup-tokens/SETUP1":
        return 200, SETUP_APPROVED
    if method == "POST" and path == "/v3/vault/payment-tokens":
        return 200, PAYMENT_TOKEN
    if method == "POST" and path == "/v1/billing/subscriptions":
        return 200, SUBSCRIPTION
    if method == "POST" and path.endswith("/void") and path.endswith("AUTH-EMPTY/void"):
        return 204, None
    return 500, {"name": "UNEXPECTED", "message": f"{method} {path}", "debug_id": "dbg-route"}


class _Router(HTTPAdapter):
    def __init__(self, records: list[dict[str, Any]]) -> None:
        super().__init__()
        self.records = records

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        path = urlparse(request.url or "").path
        method = (request.method or "").upper()
        status, payload = _dispatch(method, path)
        raw = b"" if payload is None else json.dumps(payload).encode()
        response = requests.Response()
        response.status_code = status
        response.reason = "OK" if status < 400 else "Error"
        response.url = request.url or ""
        response.headers["Content-Type"] = "application/json"
        response._content = raw
        response.request = request
        self.records.append(_record(method, path, status, request.headers.get("PayPal-Request-Id"), request.body))
        return response


def _record(method: str, path: str, status: int, request_id: Any, body: Any) -> dict[str, Any]:
    return {
        "method": method,
        "path": path,
        "status": status,
        "request_id": None if request_id in (None, "") else str(request_id),
        "body": _body(body),
    }


def _body(raw: Any) -> Any:
    if raw is None or raw == b"" or raw == "":
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text[0] not in "{[":
            return None
        return json.loads(text)
    return raw


def _header(headers: Any, name: str) -> str | None:
    if not headers:
        return None
    for key, value in dict(headers).items():
        if str(key).lower() == name.lower() and value not in (None, ""):
            return str(value)
    return None


def _httpx_client(records: list[dict[str, Any]]) -> PayPalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()
        status, payload = _dispatch(method, path)
        records.append(_record(
            method,
            path,
            status,
            request.headers.get("PayPal-Request-Id"),
            request.content,
        ))
        if payload is None:
            return httpx.Response(status)
        return httpx.Response(status, json=payload)

    return PayPalClient(
        EscalesConfig("test-client-id", "test-secret"),
        transport=httpx.MockTransport(handler),
    )


def _install(records: list[dict[str, Any]]) -> ResponseCatcher:
    catcher = ResponseCatcher()
    session = requests.Session()
    adapter = _Router(records)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    install_client(build_sandbox_client(http_client_instance=session, http_call_back=catcher))
    return catcher


def _sdk_method(raw: Any) -> str:
    if raw == "POST" or raw == "GET":
        return str(raw)
    text = str(getattr(raw, "value", raw)).upper()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _sdk_records(catcher: ResponseCatcher) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for request in catcher.requests:
        path = urlparse(request.query_url).path
        method = _sdk_method(request.http_method)
        body = _body(request.parameters) if method == "POST" else None
        rows.append(_record(
            method,
            path,
            0,
            _header(request.headers, "PayPal-Request-Id"),
            body if body is None else json.dumps(body),
        ))
    return rows


def _operations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["path"] != "/v1/oauth2/token"]


@pytest.fixture
def pins(monkeypatch: pytest.MonkeyPatch) -> _Ids:
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T12:00:00Z")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)

    def fixed() -> str:
        return FIXED_AT

    for target in (
        "app.escales.ledger.now_iso",
        "app.escales.pledges.now_iso",
        "app.escales.paypal_subscriptions.now_iso",
        "app.escales.audit.now_iso",
    ):
        monkeypatch.setattr(target, fixed)
    gen = _Ids()
    for target in (
        "app.escales.ledger.uuid.uuid4",
        "app.escales.pledges.uuid.uuid4",
        "app.escales.audit.uuid.uuid4",
    ):
        monkeypatch.setattr(target, gen)
    return gen


@pytest.fixture(autouse=True)
def _reset_gateway() -> Any:
    reset_client()
    reset_ledger()
    yield
    reset_client()
    reset_ledger()


def _pledge(**extra: Any) -> dict[str, Any]:
    doc = {
        "status": "created",
        "currency": "EUR",
        "description": "Escales",
        "history": ["created"],
        "kind": "common_fund",
        "milestone_id": "common-fund",
        "target_id": "common-fund",
    }
    doc.update(extra)
    return doc


async def _seed(doc: dict[str, Any]) -> None:
    await get_ledger().insert_pledge_once(doc)


async def _db() -> dict[str, Any]:
    return {
        "pledges": await get_ledger().list_pledges(),
        "finance": await list_finance_entries(),
        "audit": await list_entries(),
    }


async def _run_case(name: str, client: PayPalClient) -> dict[str, Any]:
    error_status: int | None = None
    issues: list[str] = []
    try:
        if name == "authorize_capture_refund":
            await _seed(_pledge(
                _id="pledge-auth",
                intent="AUTHORIZE",
                payment_mode="AUTHORIZE",
                amount_eur="20.00",
                order_id="ORDER-AUTH",
            ))
            await authorize_pledge("pledge-auth", client)
            await capture_pledge("pledge-auth", client)
            await refund_pledge("pledge-auth", client, request_key="once")
        elif name == "void":
            await _seed(_pledge(
                _id="pledge-void",
                status="authorized",
                intent="AUTHORIZE",
                payment_mode="AUTHORIZE",
                amount_eur="20.00",
                order_id="ORDER-VOID",
                authorization_id="AUTH-VOID",
                history=["created", "authorized"],
            ))
            await void_pledge("pledge-void", client)
        elif name == "capture_order":
            await _seed(_pledge(
                _id="pledge-cap",
                intent="CAPTURE",
                payment_mode="CAPTURE",
                kind="project_pledge",
                amount_eur="15.00",
                order_id="ORDER-CAP",
                milestone_id="project-1",
                target_id="project-1",
            ))
            await authorize_pledge("pledge-cap", client)
        elif name == "authorize_recover":
            await _seed(_pledge(
                _id="pledge-recover",
                intent="AUTHORIZE",
                payment_mode="AUTHORIZE",
                amount_eur="20.00",
                order_id="ORDER-RECOVER",
            ))
            await authorize_pledge("pledge-recover", client)
        elif name == "authorize_declined":
            await _seed(_pledge(
                _id="pledge-declined",
                intent="AUTHORIZE",
                payment_mode="AUTHORIZE",
                amount_eur="20.00",
                order_id="ORDER-DECLINED",
            ))
            await authorize_pledge("pledge-declined", client)
        elif name == "vault":
            created = await _create_vault_pledge(
                amount="12.00",
                description="Escales vault",
                milestone_id="common-fund",
                client=client,
                client_key="vault-key",
                contributor=None,
                kind="common_fund",
                target_id="common-fund",
            )
            await register_vault_pledge(created["_id"], client)
        elif name == "subscription":
            await list_finance_entries()
            from app.escales.ledger import record_finance
            from app.escales.paypal_subscriptions import CREW_SETUP_KEY

            await record_finance(
                "subscription_catalog_ready",
                setup_key=CREW_SETUP_KEY,
                product_id_en="PROD-EN",
                plan_id_en="P-EN",
                product_id_fr="PROD-FR",
                plan_id_fr="P-FR",
            )
            await create_crew_subscription(
                client,
                return_url="https://example.test/sub/return",
                cancel_url="https://example.test/sub/cancel",
                client_key="sub-key",
                lang="en",
            )
        else:
            raise AssertionError(name)
    except PayPalError as exc:
        error_status = exc.status
        issues = paypal_error_issues(exc.body)
    return {"error_status": error_status, "issues": issues, "db": await _db()}


def _stamp_status(calls: list[dict[str, Any]], transport: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SDK catcher has no status. Copy it from the adapter that served the call."""
    served = _operations(transport)
    assert len(calls) == len(served)
    stamped: list[dict[str, Any]] = []
    for call, source in zip(calls, served):
        merged = dict(call)
        merged["status"] = source["status"]
        stamped.append(merged)
    return stamped


def _snapshot(name: str, use_sdk: bool, monkeypatch: pytest.MonkeyPatch, gen: _Ids) -> dict[str, Any]:
    from app.escales import paypal_sdk_gateway as gateway

    gen.n = 0
    reset_ledger()
    reset_client()
    http_rows: list[dict[str, Any]] = []
    sdk_rows: list[dict[str, Any]] = []
    saved_client = gateway.client
    saved_build = gateway.build_sandbox_client

    def forbid(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("SDK client built while ESCALES_PAYPAL_SDK_ENABLED is off")

    if use_sdk:
        monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")
        catcher: ResponseCatcher | None = _install(sdk_rows)
    else:
        monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)
        gateway.client = forbid  # type: ignore[method-assign]
        gateway.build_sandbox_client = forbid  # type: ignore[method-assign]
        catcher = None
    try:
        client = _httpx_client(http_rows)
        result = asyncio.run(_run_case(name, client))
    finally:
        gateway.client = saved_client
        gateway.build_sandbox_client = saved_build
    if use_sdk:
        assert catcher is not None
        calls = _stamp_status(_operations(_sdk_records(catcher)), sdk_rows)
        assert http_rows == []
    else:
        calls = _operations(http_rows)
    result["calls"] = calls
    return result


CASES = (
    "authorize_capture_refund",
    "void",
    "capture_order",
    "authorize_recover",
    "authorize_declined",
    "vault",
    "subscription",
)


@pytest.mark.parametrize("name", CASES)
def test_write_parity_flag_on_matches_flag_off(
    name: str,
    pins: _Ids,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off = _snapshot(name, False, monkeypatch, pins)
    on = _snapshot(name, True, monkeypatch, pins)
    assert on["db"] == off["db"]
    assert on["error_status"] == off["error_status"]
    assert on["issues"] == off["issues"]
    assert on["calls"] == off["calls"]
    assert on["calls"]
    for call in on["calls"]:
        if call["method"] == "POST":
            assert call["request_id"]
    if name == "authorize_declined":
        assert on["error_status"] == 422
        assert on["issues"] == ["INSTRUMENT_DECLINED"]
        assert on["db"]["finance"] == []
    if name == "authorize_recover":
        assert on["error_status"] is None
        assert on["db"]["pledges"][0]["status"] == "authorized"
        assert on["db"]["pledges"][0]["authorization_id"] == "AUTH-R"
    if name == "authorize_capture_refund":
        assert on["db"]["pledges"][0]["status"] == "refunded"
        kinds = [row["kind"] for row in on["db"]["finance"]]
        assert kinds == ["pledge_authorized", "pledge_captured", "pledge_refunded"]
    if name == "void":
        assert on["db"]["pledges"][0]["status"] == "voided"
        assert on["db"]["finance"][-1]["kind"] == "pledge_voided"
    if name == "capture_order":
        assert on["db"]["pledges"][0]["status"] == "captured"
        assert on["db"]["pledges"][0]["capture_id"] == "CAP-ORDER"
    if name == "vault":
        assert on["db"]["pledges"][0]["status"] == "vaulted"
        assert on["db"]["pledges"][0]["vault_id"] == "VAULT1"
        assert [row["kind"] for row in on["db"]["finance"]] == ["pledge_created", "pledge_vaulted"]
    if name == "subscription":
        cache = [row for row in on["db"]["finance"] if row["kind"] == "paypal_subscription_create_cache"]
        assert cache[0]["create_response"]["subscription_id"] == "I-SUB1"
        assert cache[0]["create_response"]["status"] == "APPROVAL_PENDING"


def test_void_empty_body_is_empty_dict_on_both_paths(
    pins: _Ids,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)
    http_rows: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json=TOKEN)
        http_rows.append(request.url.path)
        return httpx.Response(204)

    client = PayPalClient(
        EscalesConfig("test-client-id", "test-secret"),
        transport=httpx.MockTransport(handler),
    )
    assert client.void_authorization("AUTH-EMPTY") == {}

    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")
    sdk_rows: list[str] = []
    session = requests.Session()

    class _Empty(HTTPAdapter):
        def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
            path = urlparse(request.url or "").path
            response = requests.Response()
            response.url = request.url or ""
            response.request = request
            if path == "/v1/oauth2/token":
                response.status_code = 200
                response.headers["Content-Type"] = "application/json"
                response._content = json.dumps(TOKEN).encode()
            else:
                response.status_code = 204
                response._content = b""
                sdk_rows.append(path)
            return response

    session.mount("https://", _Empty())
    session.mount("http://", _Empty())
    install_client(build_sandbox_client(http_client_instance=session))
    assert client.void_authorization("AUTH-EMPTY") == {}
    assert sdk_rows == ["/v2/payments/authorizations/AUTH-EMPTY/void"]
    assert http_rows == ["/v2/payments/authorizations/AUTH-EMPTY/void"]


def _subprocess(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_flag_off_writes_never_import_sdk() -> None:
    script = """
import os, sys
os.environ.pop("ESCALES_PAYPAL_SDK_ENABLED", None)
os.environ["PAYPAL_ENV"] = "sandbox"
import httpx
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient

def handler(request):
    path = request.url.path
    if path == "/v1/oauth2/token":
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
    return httpx.Response(200, json={"id": "ID1", "status": "COMPLETED", "intent": "AUTHORIZE"})

client = PayPalClient(EscalesConfig("id", "secret"), transport=httpx.MockTransport(handler))
assert client.authorize_order("ORDER1")["id"] == "ID1"
assert client.capture_order("ORDER1", idempotency_key="capture-1")["status"] == "COMPLETED"
assert client.capture_authorization("AUTH1", idempotency_key="capture-2")["id"] == "ID1"
assert client.void_authorization("AUTH1")["id"] == "ID1"
setup = client.create_setup_token("https://example.test/r", "https://example.test/c", customer_id="cust")
assert setup["id"] == "ID1"
token = client.create_payment_token("SETUP1", pledge_id="pledge-1")
assert token["id"] == "ID1"
refund = client.refund_capture("CAP1", amount_eur="5.00", idempotency_key="refund-1")
assert refund["status"] == "COMPLETED"
sub = client.create_billing_subscription(
    plan_id="P-1",
    return_url="https://example.test/r",
    cancel_url="https://example.test/c",
    idempotency_key="sub-1",
)
assert sub["id"] == "ID1"
loaded = [
    name for name in sys.modules
    if name == "paypalserversdk" or name.startswith("paypalserversdk.") or "apimatic" in name.lower()
]
assert loaded == [], loaded
"""
    env = os.environ.copy()
    env.pop("ESCALES_PAYPAL_SDK_ENABLED", None)
    env["PAYPAL_ENV"] = "sandbox"
    completed = _subprocess(script, env)
    assert completed.returncode == 0, completed.stderr


def test_live_env_write_never_imports_sdk() -> None:
    script = """
import os, sys
os.environ["ESCALES_PAYPAL_SDK_ENABLED"] = "1"
os.environ["PAYPAL_ENV"] = "live"
os.environ["PAYPAL_CLIENT_ID"] = "id"
os.environ["PAYPAL_CLIENT_SECRET"] = "secret"
import httpx
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient

def handler(request):
    if request.url.path == "/v1/oauth2/token":
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
    return httpx.Response(200, json={"id": "ID1", "status": "COMPLETED"})

client = PayPalClient(EscalesConfig("id", "secret"), transport=httpx.MockTransport(handler))
assert client.authorize_order("ORDER1")["id"] == "ID1"
loaded = [
    name for name in sys.modules
    if name == "paypalserversdk" or name.startswith("paypalserversdk.") or "apimatic" in name.lower()
]
assert loaded == [], loaded
"""
    env = os.environ.copy()
    env["PAYPAL_ENV"] = "live"
    env["ESCALES_PAYPAL_SDK_ENABLED"] = "1"
    completed = _subprocess(script, env)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("sdk_enabled", [False, True])
@pytest.mark.parametrize("operation", ["authorize", "capture", "void", "refund_full", "refund_partial", "capture_order"])
def test_replayed_writes_keep_request_id_and_payload(
    operation: str, sdk_enabled: bool, pins: _Ids, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller retry must preserve the request identity at the HTTP boundary."""
    records: list[dict[str, Any]] = []
    reset_client()
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1" if sdk_enabled else "0")
    if sdk_enabled:
        _install(records)
    client = _httpx_client(records)
    key = "replay-" + "x" * 140

    def invoke() -> dict[str, Any]:
        if operation == "authorize":
            return client.authorize_order("ORDER-AUTH", pledge_id="stable-pledge")
        if operation == "void":
            return client.void_authorization("AUTH-VOID", pledge_id="stable-pledge")
        if operation == "capture":
            return client.capture_authorization("AUTH-1", idempotency_key=key)
        if operation == "capture_order":
            return client.capture_order("ORDER-CAP", idempotency_key=key)
        return client.refund_capture(
            "CAP-AUTH", idempotency_key=key,
            amount_eur="5.00" if operation == "refund_partial" else None,
        )

    try:
        assert invoke() == invoke()
        calls = _operations(records)
        assert len(calls) == 2
        assert calls[0] == calls[1]
        assert calls[0]["request_id"]
        if operation not in {"authorize", "void"}:
            assert calls[0]["request_id"] == key[:127]
    finally:
        reset_client()
