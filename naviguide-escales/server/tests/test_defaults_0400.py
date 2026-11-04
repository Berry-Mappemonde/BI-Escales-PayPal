"""Garde les défauts configurés pour la visite des juges."""
import asyncio

import escale_watch
import film_script
import film_web_context
import story_cascade
import tavily_client
from tests.test_film_web_context import NOW, _cascade, _install
import official_store


EU_TF = "https://api.tokenfactory.nebius.com/v1"


def test_tavily_watch_defaults_on_with_key(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TAVILY_WATCH", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    assert escale_watch.watch_enabled() is True


def test_tavily_without_key_is_graceful_and_receipt_has_zero_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TAVILY_WATCH", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert escale_watch.watch_enabled() is True
    result = asyncio.run(tavily_client.search("port conditions"))
    assert result == {"results": [], "credits": 0}
    assert film_web_context.compact(None) is None

    _install(tmp_path, monkeypatch)
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_cascade, now=NOW))
    written = official_store.serve_film("fr", 150, style="written")
    assert written["receipt"]
    assert written.get("webSources", []) == []


def test_ultra_and_write_defaults_use_exact_eu_host(monkeypatch):
    for name in ("NAVIGUIDE_TF_BASE", "NAVIGUIDE_TF_BASE_EU", "NAVIGUIDE_TF_BASE_ULTRA"):
        monkeypatch.delenv(name, raising=False)
    assert story_cascade.tf_base("deep") == EU_TF
    assert story_cascade.tf_base("write") == EU_TF


def test_timeout_fallback_defaults_on(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    assert story_cascade.timeout_fallback_allowed() is True


def test_film_ultra_gate_defaults_open(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    assert film_script.film_ultra_open() is True
