"""ESCALES_PAYPAL_JS_V6_ENABLED: the browser reads `paypal_js_v6` from /features.

The flag only tells the page which PayPal browser SDK to load. It changes no
server payment route, so nothing here calls PayPal.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.escales.config import paypal_js_v6_enabled
from app.escales.ledger import reset_ledger
from app.routers.escales import router

FLAG = "ESCALES_PAYPAL_JS_V6_ENABLED"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.delenv(FLAG, raising=False)
    reset_ledger()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    reset_ledger()


def test_off_by_default(api):
    assert paypal_js_v6_enabled() is False
    flags = api.get("/api/escales/features").json()
    assert flags["paypal_js_v6"] is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "v6", "  "])
def test_stays_off_for_values_that_are_not_truthy(api, monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    assert paypal_js_v6_enabled() is False
    assert api.get("/api/escales/features").json()["paypal_js_v6"] is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " true "])
def test_on_when_set(api, monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    assert paypal_js_v6_enabled() is True
    assert api.get("/api/escales/features").json()["paypal_js_v6"] is True


@pytest.mark.parametrize(
    "paypal_env",
    [pytest.param("production", id="paypal-env-production"), pytest.param("LIVE", id="paypal-env-is-live-upper")],
)
def test_stays_off_outside_the_sandbox(monkeypatch, paypal_env):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv("PAYPAL_ENV", paypal_env)
    assert paypal_js_v6_enabled() is False


def test_missing_paypal_env_counts_as_sandbox(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.delenv("PAYPAL_ENV", raising=False)
    assert paypal_js_v6_enabled() is True


def test_the_flag_changes_nothing_else_in_features(api, monkeypatch):
    before = api.get("/api/escales/features").json()
    monkeypatch.setenv(FLAG, "true")
    after = api.get("/api/escales/features").json()
    assert {key for key in before if before[key] != after[key]} == {"paypal_js_v6"}
    assert set(before) == set(after)


def test_the_value_is_a_boolean_only(api, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    assert type(api.get("/api/escales/features").json()["paypal_js_v6"]) is bool
