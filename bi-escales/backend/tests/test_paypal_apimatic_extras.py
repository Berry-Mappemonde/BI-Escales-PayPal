"""APIMatic Payouts and Partner Referrals extras stay unloaded until the flag is on."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from app.escales.config import SANDBOX_BASE
from app.escales.paypal_apimatic_extras import (
    ApimaticExtrasDisabledError,
    ApimaticExtrasSandboxRequiredError,
    create_partner_referral,
    create_payout_batch,
    get_partner_referral,
    get_payout_batch,
)
from app.escales.paypal_client import PayPalError

_VENDOR_PREFIXES = ("payouts", "partner_referrals")
_SMOKE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "apimatic_extras_smoke.py"
_ID_PLACEHOLDER = "id-placeholder"
_SECRET_PLACEHOLDER = "secret-placeholder"


def _is_vendor_module(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _VENDOR_PREFIXES)


@pytest.fixture
def isolated_imports():
    saved_modules = {name: sys.modules[name] for name in list(sys.modules) if _is_vendor_module(name)}
    saved_path = list(sys.path)
    for name in saved_modules:
        del sys.modules[name]
    yield
    for name in list(sys.modules):
        if _is_vendor_module(name):
            del sys.modules[name]
    sys.modules.update(saved_modules)
    sys.path[:] = saved_path


@pytest.fixture
def sandbox_env(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", _ID_PLACEHOLDER)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", _SECRET_PLACEHOLDER)
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", _ID_PLACEHOLDER)
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", _SECRET_PLACEHOLDER)


def _load_smoke():
    spec = importlib.util.spec_from_file_location("apimatic_extras_smoke", _SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Payload:
    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class _SdkFailure(Exception):
    def __init__(self, status_code: int, error: object):
        super().__init__("sdk failure")
        self.status_code = status_code
        self.error = error


class _HttpFailure(Exception):
    def __init__(self, status_code: int):
        super().__init__("http failure")
        self.response = types.SimpleNamespace(status_code=status_code)


class _FakeClient:
    built: list[dict] = []

    def __init__(self, **kwargs):
        type(self).built.append(kwargs)
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def payouts_post(self, **kwargs):
        return self._dispatch("payouts_post", kwargs)

    def payouts_get(self, batch_id, **kwargs):
        return self._dispatch("payouts_get", {"id": batch_id, **kwargs})

    def partner_referrals_create(self, body, **kwargs):
        return self._dispatch("partner_referrals_create", {"body": body, **kwargs})

    def partner_referrals_read(self, referral_id, **kwargs):
        return self._dispatch("partner_referrals_read", {"id": referral_id, **kwargs})

    def _dispatch(self, name, recorded):
        type(self).calls.append((name, recorded))
        outcome = type(self).outcomes[name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def payouts(self):
        return self


def _install_sdk(module_name: str, client_name: str) -> None:
    module = types.ModuleType(module_name)
    client = type(client_name, (_FakeClient,), {})
    setattr(module, client_name, client)
    sys.modules[module_name] = module
    _FakeClient.built = []
    _FakeClient.calls = []
    _FakeClient.outcomes = {}


def _assert_sandbox_client(kwargs: dict, scopes: tuple[str, ...]) -> None:
    assert kwargs["environment"] == "production"
    assert kwargs["base_url"] == SANDBOX_BASE
    assert "api-m.paypal.com" not in kwargs["base_url"]
    assert kwargs["base_url"].startswith("https://api-m.sandbox.paypal.com")
    oauth = kwargs["oauth2"]
    assert oauth["client_id"] == _ID_PLACEHOLDER
    assert oauth["client_secret"] == _SECRET_PLACEHOLDER
    assert oauth["scopes"] == list(scopes)
    logging_options = kwargs["logging_options"]
    assert logging_options["log_request_headers"] is False
    assert logging_options["log_response_headers"] is False
    assert logging_options["log_request_body"] is False


def test_flag_off_does_not_import_vendored_sdks(monkeypatch, isolated_imports):
    monkeypatch.delenv("ESCALES_APIMATIC_EXTRAS_ENABLED", raising=False)
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    body = {"items": []}
    with pytest.raises(ApimaticExtrasDisabledError):
        create_payout_batch(body)
    with pytest.raises(ApimaticExtrasDisabledError):
        get_payout_batch("batch-1")
    with pytest.raises(ApimaticExtrasDisabledError):
        create_partner_referral(body)
    with pytest.raises(ApimaticExtrasDisabledError):
        get_partner_referral("referral-1")
    assert not any(_is_vendor_module(name) for name in sys.modules)


@pytest.mark.parametrize("env_value", ["production", "not-sandbox"])
def test_non_sandbox_refuses_before_import(monkeypatch, isolated_imports, env_value):
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "on")
    monkeypatch.setenv("PAYPAL_ENV", env_value)
    with pytest.raises(ApimaticExtrasSandboxRequiredError):
        create_payout_batch({"items": []})
    with pytest.raises(ApimaticExtrasSandboxRequiredError):
        get_payout_batch("batch-1")
    with pytest.raises(ApimaticExtrasSandboxRequiredError):
        create_partner_referral({"operations": []})
    with pytest.raises(ApimaticExtrasSandboxRequiredError):
        get_partner_referral("referral-1")
    assert not any(_is_vendor_module(name) for name in sys.modules)


def test_non_sandbox_word_refuses_before_import(monkeypatch, isolated_imports):
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "yes")
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(ApimaticExtrasSandboxRequiredError):
        get_payout_batch("batch-1")
    assert not any(_is_vendor_module(name) for name in sys.modules)


def test_missing_credentials_do_not_import_sdks(monkeypatch, isolated_imports):
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "true")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    with pytest.raises(PayPalError) as caught:
        create_payout_batch({"items": []})
    assert caught.value.status == 401
    assert caught.value.body["name"] == "MISSING_CREDENTIALS"
    assert _SECRET_PLACEHOLDER not in json.dumps(caught.value.body)
    assert not any(_is_vendor_module(name) for name in sys.modules)


@pytest.mark.parametrize(
    ("caller", "module_name", "client_name", "scopes", "outcome", "expected"),
    [
        (
            lambda: create_payout_batch({"sender_batch_header": {"sender_batch_id": "local-1"}}),
            "payouts",
            "PayoutsClient",
            ("https://uri.paypal.com/payments/payouts",),
            _Payload({"batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING"}}),
            {"batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING"}},
        ),
        (
            lambda: get_payout_batch("PB-1"),
            "payouts",
            "PayoutsClient",
            ("https://uri.paypal.com/payments/payouts",),
            _Payload({"batch_header": {"payout_batch_id": "PB-1", "batch_status": "SUCCESS"}}),
            {"batch_header": {"payout_batch_id": "PB-1", "batch_status": "SUCCESS"}},
        ),
        (
            lambda: create_partner_referral({"tracking_id": "track-1"}),
            "partner_referrals",
            "PartnerReferralsClient",
            ("https://uri.paypal.com/services/customer/partner-referrals/readwrite",),
            _Payload({"links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-1"}]}),
            {"links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-1"}]},
        ),
        (
            lambda: get_partner_referral("REF-1"),
            "partner_referrals",
            "PartnerReferralsClient",
            ("https://uri.paypal.com/services/customer/partner-referrals/readwrite",),
            _Payload({"partner_referral_id": "REF-1"}),
            {"partner_referral_id": "REF-1"},
        ),
    ],
)
def test_methods_return_sdk_dicts(
    monkeypatch, isolated_imports, sandbox_env, caller, module_name, client_name, scopes, outcome, expected
):
    _install_sdk(module_name, client_name)
    _FakeClient.outcomes = {
        "payouts_post": outcome,
        "payouts_get": outcome,
        "partner_referrals_create": outcome,
        "partner_referrals_read": outcome,
    }
    assert caller() == expected
    assert _FakeClient.built
    _assert_sandbox_client(_FakeClient.built[-1], scopes)


@pytest.mark.parametrize(
    ("caller", "module_name", "client_name", "method"),
    [
        (lambda: create_payout_batch({"items": []}), "payouts", "PayoutsClient", "payouts_post"),
        (lambda: get_payout_batch("PB-9"), "payouts", "PayoutsClient", "payouts_get"),
        (lambda: create_partner_referral({"tracking_id": "t"}), "partner_referrals", "PartnerReferralsClient", "partner_referrals_create"),
        (lambda: get_partner_referral("REF-9"), "partner_referrals", "PartnerReferralsClient", "partner_referrals_read"),
    ],
)
def test_sdk_errors_map_to_paypal_error(isolated_imports, sandbox_env, caller, module_name, client_name, method):
    _install_sdk(module_name, client_name)
    _FakeClient.outcomes = {
        method: _SdkFailure(
            403,
            _Payload(
                {
                    "name": "NOT_AUTHORIZED",
                    "debug_id": "debug-1",
                    "message": "permission has not propagated",
                    "links": [{"href": "https://example.test/path?referralToken=hidden", "rel": "action_url"}],
                    "email": "hidden@example.com",
                }
            ),
        )
    }
    with pytest.raises(PayPalError) as caught:
        caller()
    assert caught.value.status == 403
    assert caught.value.body["name"] == "NOT_AUTHORIZED"
    assert caught.value.body["debug_id"] == "debug-1"
    encoded = json.dumps(caught.value.body)
    assert "links" not in caught.value.body
    assert "referralToken" not in encoded
    assert "hidden@example.com" not in encoded
    assert _SECRET_PLACEHOLDER not in encoded


def test_http_errors_without_sdk_status_map_to_502(isolated_imports, sandbox_env):
    _install_sdk("payouts", "PayoutsClient")
    _FakeClient.outcomes = {"payouts_post": TimeoutError("timed out")}
    with pytest.raises(PayPalError) as caught:
        create_payout_batch({"items": []})
    assert caught.value.status == 502
    assert caught.value.body["name"] == "TimeoutError"


def test_response_status_is_mapped(isolated_imports, sandbox_env):
    _install_sdk("partner_referrals", "PartnerReferralsClient")
    _FakeClient.outcomes = {"partner_referrals_read": _HttpFailure(500)}
    with pytest.raises(PayPalError) as caught:
        get_partner_referral("REF-1")
    assert caught.value.status == 500
    assert caught.value.body["name"] == "_HttpFailure"


def test_smoke_report_keeps_ids_and_statuses_only():
    smoke = _load_smoke()
    report = smoke.public_report(
        payout_created={
            "batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING"},
            "items": [{"receiver": "person@example.com"}],
            "links": [{"href": "https://api-m.sandbox.paypal.com/v1/payments/payouts/PB-1?token=abc", "rel": "self"}],
        },
        payout_fetched={
            "batch_header": {"payout_batch_id": "PB-1", "batch_status": "SUCCESS"},
            "items": [{"receiver": "person@example.com"}],
        },
        referral_created={
            "links": [
                {
                    "rel": "action_url",
                    "href": "https://www.sandbox.paypal.com/bizsignup/partner/entry?referralToken=hidden-token",
                },
                {
                    "rel": "self",
                    "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-1",
                },
            ]
        },
        referral_fetched={
            "partner_referral_id": "REF-1",
            "referral_data": {"email": "person@example.com"},
            "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-1"}],
        },
    )
    assert report == {
        "payout_batch_id": "PB-1",
        "payout_create_status": "PENDING",
        "payout_get_status": "SUCCESS",
        "partner_referral_id": "REF-1",
        "partner_referral_status": "READ",
    }
    encoded = json.dumps(report)
    assert "example.com" not in encoded
    assert "referralToken" not in encoded
    assert "http" not in encoded
    assert "token" not in encoded.lower()


def test_referral_id_ignores_action_url_token():
    smoke = _load_smoke()
    payload = {
        "links": [
            {
                "rel": "action_url",
                "href": "https://www.sandbox.paypal.com/bizsignup/partner/entry?referralToken=hidden-token",
            },
            {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-7"},
        ]
    }
    assert smoke.referral_id_from(payload) == "REF-7"
    with pytest.raises(smoke.SmokeReportError) as caught:
        smoke.referral_id_from({"links": [payload["links"][0]]})
    assert caught.value.status == "missing_id"
    assert "hidden-token" not in str(caught.value)


def test_smoke_disabled_and_missing_receiver_are_status_json(monkeypatch, capsys):
    smoke = _load_smoke()
    monkeypatch.delenv("ESCALES_APIMATIC_EXTRAS_ENABLED", raising=False)
    assert smoke.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "disabled"}
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "1")
    monkeypatch.delenv("APIM9_PAYOUT_RECEIVER", raising=False)
    assert smoke.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "missing_receiver"}


def test_smoke_403_is_json_and_exit_zero(monkeypatch, capsys):
    smoke = _load_smoke()
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("APIM9_PAYOUT_RECEIVER", "person@example.com")

    def _forbidden(*_args, **_kwargs):
        raise PayPalError(403, {"name": "NOT_AUTHORIZED", "message": "person@example.com"})

    monkeypatch.setattr(smoke, "create_payout_batch", _forbidden)
    assert smoke.main() == 0
    captured = capsys.readouterr().out
    assert json.loads(captured) == {"status": "403_propagation"}
    assert "example.com" not in captured
    assert "NOT_AUTHORIZED" not in captured


def test_smoke_success_prints_only_ids_and_statuses(monkeypatch, capsys):
    smoke = _load_smoke()
    monkeypatch.setenv("ESCALES_APIMATIC_EXTRAS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("APIM9_PAYOUT_RECEIVER", "person@example.com")
    monkeypatch.setattr(
        smoke,
        "create_payout_batch",
        lambda body, **kwargs: {
            "batch_header": {"payout_batch_id": "PB-2", "batch_status": "PENDING"},
            "items": body["items"],
        },
    )
    monkeypatch.setattr(
        smoke,
        "get_payout_batch",
        lambda batch_id: {"batch_header": {"payout_batch_id": batch_id, "batch_status": "PENDING"}},
    )
    monkeypatch.setattr(
        smoke,
        "create_partner_referral",
        lambda body: {
            "links": [
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/REF-2"},
                {"rel": "action_url", "href": "https://www.sandbox.paypal.com/start?referralToken=hidden-token"},
            ]
        },
    )
    monkeypatch.setattr(
        smoke,
        "get_partner_referral",
        lambda referral_id: {"partner_referral_id": referral_id, "referral_data": {"email": "person@example.com"}},
    )
    assert smoke.main() == 0
    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert report == {
        "partner_referral_id": "REF-2",
        "partner_referral_status": "READ",
        "payout_batch_id": "PB-2",
        "payout_create_status": "PENDING",
        "payout_get_status": "PENDING",
    }
    assert "example.com" not in captured
    assert "referralToken" not in captured
    assert "http" not in captured


def test_vendored_sdks_import_when_runtime_deps_exist(isolated_imports):
    pytest.importorskip("httpx2")
    pytest.importorskip("email_validator")
    from app.escales.paypal_apimatic_extras import _build_client, _load_sdk

    payouts = _load_sdk("payouts")
    referrals = _load_sdk("partner_referrals")
    client = _build_client(
        payouts.PayoutsClient,
        client_id=_ID_PLACEHOLDER,
        client_secret=_SECRET_PLACEHOLDER,
        scopes=("https://uri.paypal.com/payments/payouts",),
    )
    try:
        template = client._server.default("/v1/payments/payouts")
        assert template.base_url == SANDBOX_BASE
        assert "api-m.paypal.com" not in template.base_url
    finally:
        client.close()
    referral = _build_client(
        referrals.PartnerReferralsClient,
        client_id=_ID_PLACEHOLDER,
        client_secret=_SECRET_PLACEHOLDER,
        scopes=("https://uri.paypal.com/services/customer/partner-referrals/readwrite",),
    )
    try:
        template = referral._server.default("/v2/customer/partner-referrals")
        assert template.base_url == SANDBOX_BASE
        assert "api-m.paypal.com" not in template.base_url
    finally:
        referral.close()
