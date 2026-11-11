"""Project onboarding on a separate PayPal Platform sandbox app.

The platform pair is used on the onboarding path and nowhere else. Every PayPal
call here goes to a stubbed transport; the "credentials" are test words.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import config
from app.escales.config import SANDBOX_BASE, load_config, load_platform_config, platform_credentials_active
from app.escales.paypal_client import PayPalClient
from app.project_onboarding import paypal_orders, service
from app.project_onboarding import webhooks as onboarding_webhooks
from app.project_onboarding.constants import DEMO_PROJECT_ID, ONBOARDING_HELD_STATUS
from app.project_onboarding.partner_referrals import RawHttpPartnerReferralsClient
from app.project_onboarding.store import reset_onboarding_store
from app.routers import escales as escales_router
from app.routers import project_onboarding as onboarding_router

MAIN_ID = "main-app-id-for-tests"
MAIN_SECRET = "main-app-secret-for-tests"
PLATFORM_ID = "platform-app-id-for-tests"
PLATFORM_SECRET = "platform-app-secret-for-tests"
MAIN_WEBHOOK = "WH-MAIN-FOR-TESTS"
PLATFORM_WEBHOOK = "WH-PLATFORM-FOR-TESTS"
EVERY_VALUE = (MAIN_ID, MAIN_SECRET, PLATFORM_ID, PLATFORM_SECRET, MAIN_WEBHOOK, PLATFORM_WEBHOOK)

WEBHOOK_HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "tx-platform",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-11T00:00:00Z",
    "PAYPAL-TRANSMISSION-SIG": "c2ln",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
}


@pytest.fixture(autouse=True)
def _main_app_only(monkeypatch):
    """Every test starts on the main app alone, in the sandbox, with the warning not yet given."""
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", MAIN_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", MAIN_SECRET)
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", MAIN_WEBHOOK)
    for name in ("PAYPAL_PLATFORM_CLIENT_ID", "PAYPAL_PLATFORM_CLIENT_SECRET", "PAYPAL_PLATFORM_WEBHOOK_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ESCALES_PAYPAL_SDK_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "1")
    monkeypatch.setattr(config, "_platform_fallback_warned", False)


@pytest.fixture
def platform(monkeypatch):
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", PLATFORM_ID)
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", PLATFORM_SECRET)


class PayPalStub:
    """Sandbox answers, and a record of which app's credentials made each call."""

    def __init__(self, *, verification_status: str = "SUCCESS"):
        self.verification_status = verification_status
        self.oauth_pairs: list[tuple[str, str]] = []
        self.resource_calls: list[tuple[str, str, str]] = []
        self.verify_bodies: list[dict] = []
        self._units: list[dict] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("Authorization", "")
        if path == "/v1/oauth2/token":
            client_id, _, client_secret = base64.b64decode(auth.removeprefix("Basic ")).decode().partition(":")
            self.oauth_pairs.append((client_id, client_secret))
            # The token names the app it was issued to, so later calls show whose token they carry.
            return httpx.Response(200, json={"access_token": f"token-of-{client_id}", "expires_in": 3600})
        self.resource_calls.append((request.method, path, auth.removeprefix("Bearer ")))
        if request.method == "POST" and path == "/v2/checkout/orders":
            body = json.loads(request.content)
            self._units = body["purchase_units"]
            return httpx.Response(201, json={
                "id": "ORDER-STUB",
                "status": "CREATED",
                "intent": body["intent"],
                "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-STUB"}],
            })
        if request.method == "GET" and path == "/v2/checkout/orders/ORDER-STUB":
            return httpx.Response(200, json={"id": "ORDER-STUB", "status": "APPROVED", "purchase_units": self._units})
        if request.method == "POST" and path == "/v2/checkout/orders/ORDER-STUB/capture":
            return httpx.Response(201, json={
                "status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": [{"id": "CAP-STUB", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and path == "/v2/checkout/orders/ORDER-STUB/authorize":
            return httpx.Response(201, json={"id": "ORDER-STUB", "purchase_units": []})
        if request.method == "POST" and path == "/v2/customer/partner-referrals":
            return httpx.Response(201, json={"links": [
                {"rel": "action_url", "href": "https://www.sandbox.paypal.com/merchantsignup?token=REF-STUB"},
                {"rel": "self", "href": f"{SANDBOX_BASE}/v2/customer/partner-referrals/REF-STUB"},
            ]})
        if request.method == "POST" and path == "/v1/notifications/verify-webhook-signature":
            self.verify_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"verification_status": self.verification_status})
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})

    def client_class(self):
        """Stands in for ``PayPalClient`` in a module: same config, this transport."""
        return lambda cfg: PayPalClient(cfg, transport=self.transport)

    def tokens_used(self) -> set[str]:
        return {token for _method, _path, token in self.resource_calls}


@pytest.fixture
def onboarding_api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_DEMO_PROJECT_CONTACT_EMAIL", "project@example.com")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    reset_onboarding_store()
    app = FastAPI()
    app.include_router(onboarding_router.router)
    app.include_router(onboarding_router.webhooks_router)
    with TestClient(app) as client:
        client.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
        yield client
    reset_onboarding_store()


# --- load_platform_config ---------------------------------------------------------


def test_platform_config_uses_the_platform_pair_when_both_are_set(platform):
    main = load_config()
    cfg = load_platform_config()
    assert (cfg.client_id, cfg.client_secret) == (PLATFORM_ID, PLATFORM_SECRET)
    # Everything but the two credentials is the main config's.
    assert (cfg.base_url, cfg.currency, cfg.env) == (main.base_url, main.currency, main.env)
    assert cfg.base_url == SANDBOX_BASE
    assert cfg.configured
    assert platform_credentials_active() is True
    # The main config is untouched.
    assert (main.client_id, main.client_secret) == (MAIN_ID, MAIN_SECRET)


@pytest.mark.parametrize(
    "client_id, client_secret",
    [(None, None), (PLATFORM_ID, None), (None, PLATFORM_SECRET), ("", ""), (PLATFORM_ID, "   "), ("  ", PLATFORM_SECRET)],
)
def test_platform_config_falls_back_to_the_main_config_when_either_is_unset(monkeypatch, client_id, client_secret):
    if client_id is not None:
        monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", client_id)
    if client_secret is not None:
        monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", client_secret)
    assert load_platform_config() == load_config()
    assert platform_credentials_active() is False


def test_platform_pair_is_trimmed(monkeypatch):
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", f"  {PLATFORM_ID}\n")
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", f" {PLATFORM_SECRET} ")
    cfg = load_platform_config()
    assert (cfg.client_id, cfg.client_secret) == (PLATFORM_ID, PLATFORM_SECRET)


@pytest.mark.parametrize(
    "env",
    [
        # Explicit ids: conftest treats a bare "live" keyword as a live-network test and skips it.
        pytest.param("live", id="paypal-env-is-live"),
        pytest.param("production", id="paypal-env-is-production"),
        pytest.param("LIVE", id="paypal-env-is-upper-live"),
    ],
)
def test_platform_config_is_refused_outside_the_sandbox(monkeypatch, platform, env):
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    monkeypatch.setenv("PAYPAL_ENV", env)
    assert platform_credentials_active() is False
    assert config.paypal_platform_webhook_id() == ""
    with pytest.raises(RuntimeError, match="sandbox only") as raised:
        load_platform_config()
    assert not any(value in str(raised.value) for value in EVERY_VALUE)
    with pytest.raises(RuntimeError, match="sandbox only"):
        service._paypal()
    with pytest.raises(RuntimeError, match="sandbox only"):
        onboarding_router._paypal_client()
    # No warning either: nothing runs there, and nothing about the pair is said.
    assert config.warn_if_platform_credentials_missing() is False


def test_a_client_cannot_be_built_on_a_non_sandbox_base_even_with_the_platform_pair(platform):
    from dataclasses import replace

    live = replace(load_platform_config(), base_url="https://api-m.paypal.com")
    with pytest.raises(ValueError, match="sandbox only"):
        PayPalClient(live)


# --- the one startup warning ------------------------------------------------------


def test_fallback_is_warned_once_and_names_only_the_missing_variable(monkeypatch, caplog):
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", PLATFORM_ID)
    with caplog.at_level(logging.WARNING, logger="escales.config"):
        assert config.warn_if_platform_credentials_missing() is True
        assert config.warn_if_platform_credentials_missing() is False
        load_platform_config()
        load_platform_config()
    warnings = [record for record in caplog.records if record.name == "escales.config"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "PAYPAL_PLATFORM_CLIENT_SECRET" in message
    assert "PAYPAL_PLATFORM_CLIENT_ID" not in message
    assert not any(value in message for value in EVERY_VALUE)
    assert not any(value in caplog.text for value in EVERY_VALUE)


def test_fallback_warning_names_both_variables_when_neither_is_set(caplog):
    with caplog.at_level(logging.WARNING, logger="escales.config"):
        assert config.warn_if_platform_credentials_missing() is True
    message = caplog.records[-1].getMessage()
    assert "PAYPAL_PLATFORM_CLIENT_ID" in message and "PAYPAL_PLATFORM_CLIENT_SECRET" in message
    assert not any(value in message for value in EVERY_VALUE)


def test_no_warning_when_the_platform_pair_is_set(platform, caplog):
    with caplog.at_level(logging.WARNING, logger="escales.config"):
        assert config.warn_if_platform_credentials_missing() is False
        load_platform_config()
    assert not [record for record in caplog.records if record.name == "escales.config"]


def test_no_warning_when_onboarding_is_switched_off(monkeypatch, caplog):
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "")
    with caplog.at_level(logging.WARNING, logger="escales.config"):
        assert config.warn_if_platform_credentials_missing() is False
    assert not caplog.records


def test_startup_gives_the_warning(monkeypatch, caplog):
    """app.main calls the warning when the escales routers are mounted."""
    source = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    mounted = source.index("app.include_router(project_onboarding.webhooks_router)")
    assert "warn_if_platform_credentials_missing()" in source[mounted:]
    assert source.count("warn_if_platform_credentials_missing()") == 1


# --- the onboarding path uses the platform app ------------------------------------


def test_onboarding_clients_are_built_from_the_platform_config(platform):
    for client in (service._paypal(), RawHttpPartnerReferralsClient()._client):
        assert (client.cfg.client_id, client.cfg.client_secret) == (PLATFORM_ID, PLATFORM_SECRET)
        assert client.cfg.base_url == SANDBOX_BASE


def test_onboarding_clients_fall_back_to_the_main_app():
    for client in (service._paypal(), RawHttpPartnerReferralsClient()._client, onboarding_router._paypal_client()):
        assert (client.cfg.client_id, client.cfg.client_secret) == (MAIN_ID, MAIN_SECRET)


def test_donation_referral_and_capture_all_use_the_platform_app(onboarding_api, monkeypatch, platform):
    stub = PayPalStub()
    monkeypatch.setattr(service, "PayPalClient", stub.client_class())

    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "10.00"},
    )
    assert created.status_code == 200
    assert created.json()["onboarding_link"]["available"] is True
    captured = onboarding_api.post(f"/api/escales/project-onboarding/donations/{created.json()['_id']}/capture")
    assert captured.status_code == 200
    assert captured.json()["status"] == ONBOARDING_HELD_STATUS
    assert captured.json()["capture_id"] == "CAP-STUB"

    # Every token was requested with the platform pair, never the main one...
    assert stub.oauth_pairs and set(stub.oauth_pairs) == {(PLATFORM_ID, PLATFORM_SECRET)}
    # ...and every PayPal call on the path carried the platform app's token.
    assert stub.tokens_used() == {f"token-of-{PLATFORM_ID}"}
    assert [(method, path) for method, path, _token in stub.resource_calls] == [
        ("POST", "/v2/checkout/orders"),
        ("POST", "/v2/customer/partner-referrals"),
        ("GET", "/v2/checkout/orders/ORDER-STUB"),
        ("POST", "/v2/checkout/orders/ORDER-STUB/capture"),
    ]
    # Nothing the API returned carries a credential.
    assert not any(value in created.text + captured.text for value in EVERY_VALUE)


def test_the_same_path_uses_the_main_app_when_the_platform_pair_is_unset(onboarding_api, monkeypatch):
    stub = PayPalStub()
    monkeypatch.setattr(service, "PayPalClient", stub.client_class())
    created = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "10.00"},
    )
    assert created.status_code == 200
    assert set(stub.oauth_pairs) == {(MAIN_ID, MAIN_SECRET)}
    assert stub.tokens_used() == {f"token-of-{MAIN_ID}"}


class _OrderReader:
    """A client that records how its order was read."""

    def __init__(self):
        self.how: list[str] = []

    def get_order(self, order_id):
        self.how.append("get_order")
        return {"id": order_id}

    def _req(self, method, path, *args, **kwargs):
        self.how.append(f"{method} {path}")
        return {"id": path.rsplit("/", 1)[-1]}


def test_platform_order_is_read_with_the_clients_own_credentials_not_the_sdk_gateway(monkeypatch, platform):
    """The Server SDK gateway only holds the main app's pair; a platform order must not go through it."""
    monkeypatch.setenv("ESCALES_PAYPAL_SDK_ENABLED", "1")
    from app.escales import paypal_sdk_gateway

    def gateway_must_not_be_used(*args, **kwargs):
        raise AssertionError("the SDK gateway (main credentials) read a platform order")

    monkeypatch.setattr(paypal_sdk_gateway, "_sdk_reads", gateway_must_not_be_used)
    stub = PayPalStub()
    client = PayPalClient(load_platform_config(), transport=stub.transport)
    assert paypal_orders.read_order(client, "ORDER-STUB")["id"] == "ORDER-STUB"
    assert stub.oauth_pairs == [(PLATFORM_ID, PLATFORM_SECRET)]
    assert stub.tokens_used() == {f"token-of-{PLATFORM_ID}"}


def test_order_read_is_unchanged_without_the_platform_pair():
    reader = _OrderReader()
    assert paypal_orders.read_order(reader, "ORDER-1") == {"id": "ORDER-1"}
    assert reader.how == ["get_order"]


def test_order_read_goes_direct_with_the_platform_pair(platform):
    reader = _OrderReader()
    assert paypal_orders.read_order(reader, "ORDER-1") == {"id": "ORDER-1"}
    assert reader.how == ["GET /v2/checkout/orders/ORDER-1"]


# --- everything else keeps the main app -------------------------------------------


def test_a_pledge_order_still_uses_the_main_client(monkeypatch, platform):
    stub = PayPalStub()
    monkeypatch.setattr(escales_router, "_client_factory", None)
    monkeypatch.setattr(escales_router, "PayPalClient", stub.client_class())

    client = escales_router._paypal()
    assert (client.cfg.client_id, client.cfg.client_secret) == (MAIN_ID, MAIN_SECRET)
    order = client.create_authorize_order("20.00", "Sponsored miles", "pledge-1", idempotency_key="pledge-key-1")
    assert order["id"] == "ORDER-STUB"

    assert stub.oauth_pairs == [(MAIN_ID, MAIN_SECRET)]
    assert stub.tokens_used() == {f"token-of-{MAIN_ID}"}
    assert [(method, path) for method, path, _token in stub.resource_calls] == [("POST", "/v2/checkout/orders")]


def test_the_two_apps_never_share_a_token(platform):
    """One transport, both clients: each asks for its own token and uses only that one."""
    stub = PayPalStub()
    main = PayPalClient(load_config(), transport=stub.transport)
    platform_client = PayPalClient(load_platform_config(), transport=stub.transport)
    main.create_authorize_order("20.00", "Sponsored miles", "pledge-1", idempotency_key="pledge-key-1")
    paypal_orders.read_order(platform_client, "ORDER-STUB")
    main.create_authorize_order("5.00", "Meal", "pledge-2", idempotency_key="pledge-key-2")
    assert sorted(stub.oauth_pairs) == sorted([(MAIN_ID, MAIN_SECRET), (PLATFORM_ID, PLATFORM_SECRET)])
    assert [(path, token) for _method, path, token in stub.resource_calls] == [
        ("/v2/checkout/orders", f"token-of-{MAIN_ID}"),
        ("/v2/checkout/orders/ORDER-STUB", f"token-of-{PLATFORM_ID}"),
        ("/v2/checkout/orders", f"token-of-{MAIN_ID}"),
    ]


def test_the_sdk_gateway_and_the_main_loader_ignore_the_platform_pair(monkeypatch, platform):
    assert (load_config().client_id, load_config().client_secret) == (MAIN_ID, MAIN_SECRET)
    gateway = (Path(__file__).resolve().parent.parent / "app" / "escales" / "paypal_sdk_gateway.py").read_text(encoding="utf-8")
    assert "PAYPAL_PLATFORM" not in gateway
    assert "load_platform_config" not in gateway


def _app_files_matching(pattern: str) -> set[str]:
    app_dir = Path(__file__).resolve().parent.parent / "app"
    compiled = re.compile(pattern)
    return {
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if compiled.search(path.read_text(encoding="utf-8"))
    }


def test_only_the_onboarding_path_can_reach_the_platform_config():
    """The platform config and its helpers are used by the onboarding path and nowhere else."""
    allowed = {
        "escales/config.py",  # defines them
        "main.py",  # the startup warning only
        "routers/project_onboarding.py",
        "project_onboarding/service.py",
        "project_onboarding/partner_referrals.py",
        "project_onboarding/webhooks.py",
        "project_onboarding/paypal_orders.py",
    }
    users = _app_files_matching(r"load_platform_config|platform_credentials|paypal_platform_webhook_id")
    assert users <= allowed, f"platform config reachable from: {sorted(users - allowed)}"
    assert {"project_onboarding/service.py", "project_onboarding/partner_referrals.py",
            "project_onboarding/webhooks.py", "routers/project_onboarding.py"} <= users
    # main.py may only warn; it must not build a config.
    main_py = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert "load_platform_config" not in main_py


def test_the_platform_variables_are_read_in_two_places_only():
    """config.py, and the optional APIMatic Partner Referrals client that already read the same
    pair before this change (referrals only, behind its own flag, not modified here)."""
    assert _app_files_matching(r"PAYPAL_PLATFORM_") <= {
        "escales/config.py",
        "escales/paypal_apimatic_extras/__init__.py",
        "project_onboarding/webhooks.py",  # a docstring naming the webhook variable
    }


# --- /status ----------------------------------------------------------------------


def test_status_reports_platform_credentials_as_a_boolean_only(onboarding_api, monkeypatch):
    off = onboarding_api.get("/api/escales/project-onboarding/status")
    assert off.status_code == 200
    assert off.json()["platform_credentials"] is False

    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", PLATFORM_ID)
    half = onboarding_api.get("/api/escales/project-onboarding/status")
    assert half.json()["platform_credentials"] is False

    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", PLATFORM_SECRET)
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    on = onboarding_api.get("/api/escales/project-onboarding/status")
    assert on.json()["platform_credentials"] is True
    assert set(on.json()) == {"enabled", "email_enabled", "demo_project_id", "platform_credentials"}
    for response in (off, half, on):
        assert not any(value in response.text for value in EVERY_VALUE)


def test_status_is_false_outside_the_sandbox(onboarding_api, monkeypatch, platform):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    assert onboarding_api.get("/api/escales/project-onboarding/status").json()["platform_credentials"] is False


# --- the merchant-onboarding webhook ----------------------------------------------


def _deliver_webhook(api: TestClient, event_id: str):
    payload = {
        "id": event_id,
        "event_type": "MERCHANT.ONBOARDING.COMPLETED",
        "resource": {"tracking_id": DEMO_PROJECT_ID, "merchant_id": "MERCH-STUB"},
    }
    return api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=WEBHOOK_HEADERS,
        content=json.dumps(payload),
    )


def test_webhook_uses_the_platform_webhook_id_with_the_platform_app(onboarding_api, monkeypatch, platform):
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    stub = PayPalStub()
    monkeypatch.setattr(onboarding_router, "PayPalClient", stub.client_class())

    response = _deliver_webhook(onboarding_api, "WH-PLATFORM-1")

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert stub.verify_bodies[0]["webhook_id"] == PLATFORM_WEBHOOK
    assert stub.oauth_pairs == [(PLATFORM_ID, PLATFORM_SECRET)]
    assert stub.tokens_used() == {f"token-of-{PLATFORM_ID}"}
    assert not any(value in response.text for value in EVERY_VALUE)


def test_webhook_keeps_the_existing_id_and_the_app_that_owns_it(onboarding_api, monkeypatch, platform):
    """No platform webhook id: the existing id is verified by the main app, which it is registered on."""
    stub = PayPalStub()
    monkeypatch.setattr(onboarding_router, "PayPalClient", stub.client_class())

    response = _deliver_webhook(onboarding_api, "WH-MAIN-1")

    assert response.status_code == 200
    assert stub.verify_bodies[0]["webhook_id"] == MAIN_WEBHOOK
    assert stub.oauth_pairs == [(MAIN_ID, MAIN_SECRET)]


def test_webhook_without_any_platform_variable_is_unchanged(onboarding_api, monkeypatch):
    stub = PayPalStub()
    monkeypatch.setattr(onboarding_router, "PayPalClient", stub.client_class())
    assert _deliver_webhook(onboarding_api, "WH-MAIN-2").status_code == 200
    assert stub.verify_bodies[0]["webhook_id"] == MAIN_WEBHOOK
    assert stub.oauth_pairs == [(MAIN_ID, MAIN_SECRET)]


def test_platform_webhook_id_alone_is_used_with_the_fallback_credentials(onboarding_api, monkeypatch):
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    stub = PayPalStub()
    monkeypatch.setattr(onboarding_router, "PayPalClient", stub.client_class())
    assert _deliver_webhook(onboarding_api, "WH-PLATFORM-2").status_code == 200
    assert stub.verify_bodies[0]["webhook_id"] == PLATFORM_WEBHOOK
    assert stub.oauth_pairs == [(MAIN_ID, MAIN_SECRET)]


def test_webhook_is_rejected_when_paypal_does_not_verify_it(onboarding_api, monkeypatch, platform):
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    stub = PayPalStub(verification_status="FAILURE")
    monkeypatch.setattr(onboarding_router, "PayPalClient", stub.client_class())
    response = _deliver_webhook(onboarding_api, "WH-PLATFORM-3")
    assert response.status_code == 401
    assert not any(value in response.text for value in EVERY_VALUE)


def test_webhook_id_helpers():
    assert onboarding_webhooks.onboarding_webhook_id() == MAIN_WEBHOOK
    assert onboarding_webhooks.onboarding_webhook_config() == load_config()


def test_pledge_webhooks_keep_the_main_webhook_id(monkeypatch, platform):
    monkeypatch.setenv("PAYPAL_PLATFORM_WEBHOOK_ID", PLATFORM_WEBHOOK)
    assert config.paypal_webhook_id() == MAIN_WEBHOOK
