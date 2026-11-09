"""PayPal Server SDK read gateway: stubbed transport, flag off, httpx parity."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter

from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.paypal_sdk_gateway import (
    build_sandbox_client,
    install_client,
    reset_client,
)
from app.escales.paypal_txn_search import clamp_transaction_search_range
from paypalserversdk.http.http_call_back import HttpCallBack

BACKEND = Path(__file__).resolve().parents[1]
ORDER = {
    "id": "ORDER1",
    "intent": "AUTHORIZE",
    "status": "COMPLETED",
    "create_time": "2026-11-12T08:00:00Z",
    "purchase_units": [{
        "reference_id": "pledge-1",
        "description": "Escales",
        "custom_id": "pledge-1",
        "amount": {"currency_code": "EUR", "value": "20.00"},
    }],
    "links": [{
        "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER1",
        "rel": "self",
        "method": "GET",
    }],
}
AUTHORIZATION = {
    "id": "AUTH1",
    "status": "CREATED",
    "amount": {"currency_code": "EUR", "value": "20.00"},
    "expiration_time": "2026-12-11T08:00:00Z",
    "create_time": "2026-11-12T08:00:00Z",
    "update_time": "2026-11-12T08:00:00Z",
}
SETUP_TOKEN = {
    "id": "SETUP1",
    "status": "APPROVED",
    "customer": {"id": "cust-1"},
    "payment_source": {
        "paypal": {"usage_type": "MERCHANT", "permit_multiple_payment_tokens": False},
    },
    "links": [{
        "href": "https://api-m.sandbox.paypal.com/v3/vault/setup-tokens/SETUP1",
        "rel": "self",
        "method": "GET",
    }],
}
PLAN = {
    "id": "P-1",
    "product_id": "PROD-1",
    "name": "Crew supporter",
    "status": "ACTIVE",
    "description": "Monthly crew support",
    "quantity_supported": False,
    "create_time": "2026-11-12T08:00:00Z",
    "billing_cycles": [{
        "frequency": {"interval_unit": "MONTH", "interval_count": 1},
        "tenure_type": "REGULAR",
        "sequence": 1,
        "total_cycles": 1,
        "pricing_scheme": {"fixed_price": {"value": "5.00", "currency_code": "EUR"}},
    }],
    "payment_preferences": {
        "auto_bill_outstanding": True,
        "setup_fee_failure_action": "CONTINUE",
        "payment_failure_threshold": 3,
    },
}
PLANS = {
    "total_items": 1,
    "total_pages": 1,
    "plans": [PLAN],
    "links": [{
        "href": "https://api-m.sandbox.paypal.com/v1/billing/plans?product_id=PROD-1",
        "rel": "self",
        "method": "GET",
    }],
}
SUBSCRIPTION = {
    "id": "I-SUB1",
    "plan_id": "P-1",
    "status": "ACTIVE",
    "start_time": "2026-11-12T08:00:00Z",
    "quantity": "1",
    "create_time": "2026-11-12T08:00:00Z",
}
SEARCH_START = "2026-11-01T00:00:00+00:00"
SEARCH_END = "2026-11-08T00:00:00+00:00"
SEARCH = {
    "start_date": SEARCH_START,
    "end_date": SEARCH_END,
    "page": 1,
    "total_items": 1,
    "total_pages": 1,
    "transaction_details": [{
        "transaction_info": {
            "transaction_id": "TXN1",
            "transaction_status": "S",
        },
    }],
}


class ResponseCatcher(HttpCallBack):
    """Records each request the SDK sends, including the token POST."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.response: Any = None

    def on_before_request(self, request: Any) -> None:
        self.requests.append(request)

    def on_after_response(self, response: Any) -> None:
        self.response = response


class _JsonAdapter(HTTPAdapter):
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        super().__init__()
        self.payload = payload
        self.status = status

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        url = request.url or ""
        if "/v1/oauth2/token" in url:
            raw = json.dumps({
                "access_token": "tok",
                "expires_in": 3200,
                "token_type": "Bearer",
            }).encode()
            status = 200
            reason = "OK"
        else:
            raw = json.dumps(self.payload).encode()
            status = self.status
            reason = "OK" if status < 400 else "Error"
        response = requests.Response()
        response.status_code = status
        response.reason = reason
        response.url = url
        response.headers["Content-Type"] = "application/json"
        response._content = raw
        response.request = request
        return response


def _session(payload: dict[str, Any], *, status: int = 200) -> requests.Session:
    session = requests.Session()
    session.mount("https://", _JsonAdapter(payload, status=status))
    session.mount("http://", _JsonAdapter(payload, status=status))
    return session


def _httpx_client(payload: dict[str, Any]) -> PayPalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3000})
        return httpx.Response(200, json=payload)

    return PayPalClient(
        EscalesConfig("test-client-id", "test-secret"),
        transport=httpx.MockTransport(handler),
    )


def _operation(catcher: ResponseCatcher) -> Any:
    calls = [
        request for request in catcher.requests
        if "/v1/oauth2/token" not in request.query_url
    ]
    assert len(calls) == 1
    return calls[0]


@pytest.fixture(autouse=True)
def _reset_sdk_client() -> Any:
    reset_client()
    yield
    reset_client()


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")


def _install(payload: dict[str, Any], *, status: int = 200) -> ResponseCatcher:
    catcher = ResponseCatcher()
    install_client(build_sandbox_client(
        http_client_instance=_session(payload, status=status),
        http_call_back=catcher,
    ))
    return catcher


CASES: list[tuple[str, dict[str, Any], Callable[[PayPalClient], dict[str, Any]], str, dict[str, list[str]]]] = [
    (
        "get_order",
        ORDER,
        lambda client: client.get_order("ORDER1"),
        "/v2/checkout/orders/ORDER1",
        {},
    ),
    (
        "get_authorization",
        AUTHORIZATION,
        lambda client: client.get_authorization("AUTH1"),
        "/v2/payments/authorizations/AUTH1",
        {},
    ),
    (
        "get_setup_token",
        SETUP_TOKEN,
        lambda client: client.get_setup_token("SETUP1"),
        "/v3/vault/setup-tokens/SETUP1",
        {},
    ),
    (
        "get_billing_plan",
        PLAN,
        lambda client: client.get_billing_plan("P-1"),
        "/v1/billing/plans/P-1",
        {},
    ),
    (
        "list_billing_plans",
        PLANS,
        lambda client: client.list_billing_plans(product_id="PROD-1", page_size=20),
        "/v1/billing/plans",
        {"product_id": ["PROD-1"], "page_size": ["20"], "total_required": ["true"]},
    ),
    (
        "get_subscription",
        SUBSCRIPTION,
        lambda client: client.get_subscription("I-SUB1"),
        "/v1/billing/subscriptions/I-SUB1",
        {},
    ),
    (
        "search_transactions",
        SEARCH,
        lambda client: client.search_transactions(start_date=SEARCH_START, end_date=SEARCH_END),
        "/v1/reporting/transactions",
        {
            "start_date": [SEARCH_START],
            "end_date": [SEARCH_END],
            "fields": ["all"],
            "page_size": ["100"],
        },
    ),
]


@pytest.mark.parametrize(
    ("name", "payload", "call", "path", "query"),
    CASES,
    ids=[case[0] for case in CASES],
)
def test_sdk_dict_matches_httpx_and_request(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    payload: dict[str, Any],
    call: Callable[[PayPalClient], dict[str, Any]],
    path: str,
    query: dict[str, list[str]],
) -> None:
    fixed = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr("app.escales.paypal_txn_search.real_utc_now", lambda: fixed)
    monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)
    http_client = _httpx_client(payload)
    http_dict = call(http_client)

    _enable(monkeypatch)
    catcher = _install(payload)
    sdk_dict = call(http_client)

    assert sdk_dict == http_dict
    assert sdk_dict == payload
    request = _operation(catcher)
    assert request.http_method == "GET"
    parsed = urlparse(request.query_url)
    assert parsed.path == path
    assert parse_qs(parsed.query) == query
    assert name


def test_search_transactions_keeps_clamped_window(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(
        "app.escales.paypal_txn_search.real_utc_now",
        lambda: fixed,
    )
    _enable(monkeypatch)
    catcher = _install(SEARCH)
    client = _httpx_client(SEARCH)
    client.search_transactions(
        start_date="2026-11-01T00:00:00+00:00",
        end_date="2026-12-31T00:00:00+00:00",
    )
    request = _operation(catcher)
    parsed = urlparse(request.query_url)
    found = parse_qs(parsed.query)
    start_date, end_date = clamp_transaction_search_range(
        "2026-11-01T00:00:00+00:00",
        "2026-12-31T00:00:00+00:00",
        now=fixed,
    )
    assert found["start_date"] == [start_date]
    assert found["end_date"] == [end_date]
    assert "2026-12-31" not in request.query_url
    assert found["fields"] == ["all"]
    assert found["page_size"] == ["100"]


def test_api_exception_maps_to_paypal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    _install(
        {
            "name": "RESOURCE_NOT_FOUND",
            "message": "missing",
            "debug_id": "dbg1",
            "details": [{"issue": "INVALID_RESOURCE_ID", "description": "missing"}],
        },
        status=404,
    )
    client = _httpx_client(ORDER)
    with pytest.raises(PayPalError) as excinfo:
        client.get_order("MISSING")
    assert excinfo.value.status == 404
    assert "RESOURCE_NOT_FOUND" in str(excinfo.value.body)
    assert "dbg1" in str(excinfo.value.body)


def test_live_env_refuses_before_sdk_import() -> None:
    script = (
        "import os, sys\n"
        "os.environ['ESCALES_PAYPAL_SDK_ENABLED'] = '1'\n"
        "os.environ['PAYPAL_ENV'] = 'live'\n"
        "os.environ['PAYPAL_CLIENT_ID'] = 'id'\n"
        "os.environ['PAYPAL_CLIENT_SECRET'] = 'secret'\n"
        "from app.escales.paypal_sdk_gateway import build_sandbox_client\n"
        "try:\n"
        "    build_sandbox_client()\n"
        "except RuntimeError as exc:\n"
        "    assert 'sandbox' in str(exc)\n"
        "else:\n"
        "    raise SystemExit('expected refusal')\n"
        "loaded = [\n"
        "    name for name in sys.modules\n"
        "    if name == 'paypalserversdk'\n"
        "    or name.startswith('paypalserversdk.')\n"
        "    or 'apimatic' in name.lower()\n"
        "]\n"
        "assert loaded == [], loaded\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env={**os.environ, "PAYPAL_ENV": "live", "ESCALES_PAYPAL_SDK_ENABLED": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_flag_off_imports_no_sdk_and_uses_httpx() -> None:
    script = (
        "import os, sys\n"
        "os.environ.pop('ESCALES_PAYPAL_SDK_ENABLED', None)\n"
        "os.environ['PAYPAL_ENV'] = 'sandbox'\n"
        "import httpx\n"
        "from app.escales.config import EscalesConfig\n"
        "from app.escales.paypal_client import PayPalClient\n"
        "def handler(request):\n"
        "    if request.url.path == '/v1/oauth2/token':\n"
        "        return httpx.Response(200, json={'access_token': 'tok', 'expires_in': 300})\n"
        "    return httpx.Response(200, json={'id': 'ORDER1', 'status': 'CREATED', 'intent': 'AUTHORIZE'})\n"
        "client = PayPalClient(EscalesConfig('id', 'secret'), transport=httpx.MockTransport(handler))\n"
        "assert client.get_order('ORDER1')['status'] == 'CREATED'\n"
        "loaded = [\n"
        "    name for name in sys.modules\n"
        "    if name == 'paypalserversdk'\n"
        "    or name.startswith('paypalserversdk.')\n"
        "    or 'apimatic' in name.lower()\n"
        "]\n"
        "assert loaded == [], loaded\n"
    )
    env = os.environ.copy()
    env.pop("ESCALES_PAYPAL_SDK_ENABLED", None)
    env["PAYPAL_ENV"] = "sandbox"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
