"""Captain rate limit and LLM daily cap. Both are off unless production is on."""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import llm
from app.escales.config import limits_enabled
from app.escales.pledges import reset_ledger
from app.escales.rate_limit import (
    RateLimited,
    captain_rate_key,
    client_ip,
    hit,
    per_day,
    per_minute,
    reset,
    trusted_proxy_hops,
)
from app.escales.captain import chat
from app.routers.escales import router, set_paypal_client_factory
from test_llm_cascade import _openai, _transport

ROOT = Path(__file__).resolve().parents[2]
FR = "Je parraine 5 milles près de Brest"
EN = "I'd like to sponsor 5 nautical miles near Brest"

_NO_XFF = object()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    reset()
    reset_ledger()
    llm.reset_llm_budget()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)
    reset()
    reset_ledger()
    llm.reset_llm_budget()


def _chat(
    client,
    message,
    ip="203.0.113.10",
    accept_language="",
    lang=None,
    headers=None,
    *,
    forwarded_for=_NO_XFF,
):
    req_headers = dict(headers or {})
    if forwarded_for is _NO_XFF:
        req_headers.setdefault("x-forwarded-for", ip)
    elif forwarded_for:
        req_headers["x-forwarded-for"] = forwarded_for
    if accept_language:
        req_headers["accept-language"] = accept_language
    payload = {"message": message}
    if lang:
        payload["lang"] = lang
    return client.post("/api/escales/captain/chat", json=payload, headers=req_headers)


def _review(client, ip="203.0.113.10", accept_language="", lang=None):
    headers = {"x-forwarded-for": ip}
    if accept_language:
        headers["accept-language"] = accept_language
    params = {}
    if lang:
        params["lang"] = lang
    return client.post("/api/escales/captain/review/dep-mayotte", headers=headers, params=params)


def test_limits_follow_production_unless_overridden(monkeypatch):
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    assert limits_enabled() is False
    monkeypatch.setenv("ESCALES_ENV", "development")
    assert limits_enabled() is False
    monkeypatch.setenv("ESCALES_ENV", "production")
    assert limits_enabled() is True
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "false")
    assert limits_enabled() is False
    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "true")
    assert limits_enabled() is True
    monkeypatch.delenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", raising=False)
    monkeypatch.delenv("ESCALES_CAPTAIN_RATE_PER_DAY", raising=False)
    monkeypatch.delenv("ESCALES_LLM_DAILY_CAP", raising=False)
    assert per_minute() == 10
    assert per_day() == 100
    assert llm.llm_daily_cap() == 100


def test_env_invalid_rate_limits_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "not-a-number")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "0")
    assert per_minute() == 10
    assert per_day() == 100
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "")
    monkeypatch.delenv("ESCALES_CAPTAIN_RATE_PER_DAY", raising=False)
    assert per_minute() == 10
    assert per_day() == 100


def test_development_does_not_limit_captain_routes(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "1")
    for _ in range(4):
        response = _chat(api, FR)
        assert response.status_code == 200, response.text
    review = _review(api)
    assert review.status_code == 200, review.text


def test_development_calls_are_not_counted_when_production_turns_on(monkeypatch):
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    reset()
    hit("203.0.113.8")
    hit("203.0.113.8")
    monkeypatch.setenv("ESCALES_ENV", "production")
    hit("203.0.113.8")
    with pytest.raises(RateLimited) as raised:
        hit("203.0.113.8")
    assert raised.value.kind == "minute"


def test_production_minute_cap_is_localized(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "2")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "100")
    assert _chat(api, FR).status_code == 200
    assert _review(api).status_code == 200
    blocked = _chat(api, FR, accept_language="en")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == (
        "Trop de requêtes. Réessayez plus tard. Le capitaine accepte 2 par minute."
    )
    assert int(blocked.headers.get("retry-after", "0")) >= 1
    english = _review(api, ip="203.0.113.11", accept_language="en-GB,en;q=0.8", lang="en")
    assert english.status_code == 200
    assert _review(api, ip="203.0.113.11", accept_language="en-GB", lang="en").status_code == 200
    again = _review(api, ip="203.0.113.11", accept_language="en-GB,en;q=0.8", lang="en")
    assert again.status_code == 429
    assert again.json()["detail"] == (
        "Too many requests. Try again later. The captain accepts 2 per minute."
    )
    chat_en = _chat(api, EN, ip="203.0.113.12", lang="en")
    assert chat_en.status_code == 200
    assert _chat(api, EN, ip="203.0.113.12", lang="en").status_code == 200
    third = _chat(api, EN, ip="203.0.113.12", accept_language="fr", lang="en")
    assert third.status_code == 429
    assert third.json()["detail"] == (
        "Too many requests. Try again later. The captain accepts 2 per minute."
    )


def test_production_day_cap_is_localized(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "10")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "2")
    assert _chat(api, FR, ip="203.0.113.20").status_code == 200
    assert _chat(api, FR, ip="203.0.113.20").status_code == 200
    blocked = _chat(api, FR, ip="203.0.113.20")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == (
        "Trop de requêtes. Réessayez plus tard. Le capitaine accepte 2 par jour."
    )
    other = _chat(api, EN, ip="198.51.100.4")
    assert other.status_code == 200


def test_explicit_override_switches_either_mode(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    assert _chat(api, FR, ip="203.0.113.30").status_code == 200
    blocked = _chat(api, FR, ip="203.0.113.30")
    assert blocked.status_code == 429
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "off")
    for _ in range(3):
        response = _chat(api, FR, ip="203.0.113.31")
        assert response.status_code == 200, response.text


def test_minute_window_opens_again(monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "100")
    reset()
    base = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc)
    hit("203.0.113.40", now=base)
    with pytest.raises(RateLimited):
        hit("203.0.113.40", now=base + dt.timedelta(seconds=30))
    hit("203.0.113.40", now=base + dt.timedelta(seconds=61))


def test_pledges_stay_open_when_the_captain_is_limited(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")

    class FakePayPal:
        def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
            return {
                "id": "ORDER1",
                "status": "CREATED",
                "intent": "AUTHORIZE",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
            }

    set_paypal_client_factory(lambda: FakePayPal())
    assert _chat(api, FR, ip="203.0.113.50").status_code == 200
    assert _chat(api, FR, ip="203.0.113.50").status_code == 429
    created = api.post(
        "/api/escales/pledges",
        json={"amount_eur": "20.00", "description": "20 milles", "milestone_id": "dep-mayotte"},
        headers={"x-forwarded-for": "203.0.113.50", "PayPal-Request-Id": "rate-pledge"},
    )
    assert created.status_code == 200, created.text


def test_rotating_session_header_cannot_escape_ip_bucket(api, monkeypatch):
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    base = {"x-forwarded-for": "203.0.113.60"}
    first = _chat(api, FR, headers={**base, "x-escales-session": "tab-a"})
    assert first.status_code == 200, first.text
    blocked = _chat(api, FR, headers={**base, "x-escales-session": "tab-a"})
    assert blocked.status_code == 429
    rotated = _chat(api, FR, headers={**base, "x-escales-session": "tab-b"})
    assert rotated.status_code == 429
    no_session = _chat(api, FR, headers=base)
    assert no_session.status_code == 429
    other_ip = _chat(api, FR, headers={"x-forwarded-for": "203.0.113.61", "x-escales-session": "tab-a"})
    assert other_ip.status_code == 200, other_ip.text


def test_rotating_sessions_share_the_daily_ip_cap(monkeypatch):
    import datetime as dt

    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_DAY", "3")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "100")
    reset()
    start = dt.datetime(2027, 6, 12, 8, 0, tzinfo=dt.timezone.utc)
    for n in range(3):
        hit(captain_rate_key("198.51.100.7", f"rot-{n}"), now=start + dt.timedelta(minutes=n))
    with pytest.raises(RateLimited) as caught:
        hit(captain_rate_key("198.51.100.7", "rot-99"), now=start + dt.timedelta(minutes=5))
    assert caught.value.kind == "day"
    hit(captain_rate_key("198.51.100.8", "rot-99"), now=start + dt.timedelta(minutes=5))
    reset()


def test_xff_client_ip_parsing(monkeypatch):
    monkeypatch.setenv("ESCALES_TRUSTED_PROXY_HOPS", "1")
    assert trusted_proxy_hops() == 1
    assert client_ip("203.0.113.55, 10.0.0.2", "127.0.0.1") == "203.0.113.55"
    assert client_ip(" 203.0.113.55 , 10.0.0.2 ", "127.0.0.1") == "203.0.113.55"
    assert client_ip("", "10.0.0.5") == "10.0.0.5"
    monkeypatch.setenv("ESCALES_TRUSTED_PROXY_HOPS", "0")
    assert client_ip("203.0.113.55, 10.0.0.2", "10.0.0.5") == "10.0.0.5"


def test_xff_leftmost_ip_shares_rate_bucket(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    first = _chat(api, FR, forwarded_for="203.0.113.77, 10.0.0.1")
    assert first.status_code == 200
    second = _chat(api, FR, forwarded_for="203.0.113.77, 198.51.100.9")
    assert second.status_code == 429
    assert "Réessayez plus tard" in second.json()["detail"]


def test_rate_limit_without_xff_uses_socket_host(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "2")
    for _ in range(2):
        assert _chat(api, FR, forwarded_for=None).status_code == 200
    blocked = _chat(api, FR, forwarded_for=None)
    assert blocked.status_code == 429


def test_captain_rate_key_composes_ip_and_session():
    assert captain_rate_key("1.2.3.4", "") == "1.2.3.4"
    assert captain_rate_key("1.2.3.4", "uuid") == "1.2.3.4|uuid"


def test_render_and_readme_document_the_production_gate():
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "key: ESCALES_ENV" in blueprint
    assert "value: production" in blueprint
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    assert "ESCALES_ENV" in readme
    assert "development" in readme
    assert "ESCALES_RATE_LIMIT_ENABLED" in readme
    assert "ESCALES_TRUSTED_PROXY_HOPS" in readme
    assert "ESCALES_TRUSTED_PROXY_HOPS" in blueprint


def test_development_does_not_cap_llm_usage(monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_LLM_DAILY_CAP", "1")
    llm.reset_llm_budget()
    assert llm.consume_llm_call() is True
    assert llm.consume_llm_call() is True
    assert llm.llm_calls_today() == 0
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.delenv("ESCALES_LLM_NEBIUS_ENABLED", raising=False)
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _openai("Noted.", llm.NIM_MODEL),
            _openai("Still noted.", llm.NIM_MODEL),
        ],
    })

    async def stay_open():
        return None

    client.aclose = stay_open
    monkeypatch.setattr(llm, "_client", lambda: client)

    async def body():
        first = await chat("Je parraine 20 milles près de Mayotte")
        second = await chat("Je parraine 10 milles près de Brest")
        assert first["model_source"]["provider"] == "nim"
        assert second["model_source"]["provider"] == "nim"
        assert len(seen) == 2

    asyncio.run(body())


def test_production_llm_cap_falls_back_to_the_rules(monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_LLM_DAILY_CAP", "1")
    llm.reset_llm_budget()
    morning = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc)
    assert llm.consume_llm_call(morning) is True
    assert llm.consume_llm_call(morning) is False
    assert llm.consume_llm_call(morning + dt.timedelta(days=1)) is True
    llm.reset_llm_budget()
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.delenv("ESCALES_LLM_NEBIUS_ENABLED", raising=False)
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _openai("Noted.", llm.NIM_MODEL),
            _openai("should not be sent", llm.NIM_MODEL),
        ],
    })

    async def stay_open():
        return None

    client.aclose = stay_open
    monkeypatch.setattr(llm, "_client", lambda: client)

    async def body():
        first = await chat("Je parraine 20 milles près de Mayotte", lang="fr")
        assert first["model_source"]["provider"] == "nim"
        second = await chat("Je parraine 10 milles près de Brest", lang="fr")
        assert second["model_source"] == {"provider": "rules", "model": ""}
        assert "10,00 €" in second["reply"]
        assert "10 milles parrainés" in second["reply"]
        assert len(seen) == 1

    asyncio.run(body())


def test_override_false_removes_the_llm_cap_in_production(monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("ESCALES_LLM_DAILY_CAP", "1")
    llm.reset_llm_budget()
    assert llm.consume_llm_call() is True
    assert llm.consume_llm_call() is True
    assert llm.llm_calls_today() == 0
