"""NAVIGUIDE_OFFLINE=1 : aucun HTTP sortant."""
from __future__ import annotations

import pytest

import offline


def test_offline_outgoing_http_raises(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    offline.install_http_guard()
    import httpx

    with pytest.raises(offline.OfflineError, match="HTTP sortant interdit"):
        httpx.get("https://example.com/atlas")


def test_offline_local_http_is_allowed(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    offline.install_http_guard()
    offline.deny_outgoing("http://127.0.0.1:8010/voyage/official")
    offline.deny_outgoing("http://localhost:5174/")


def test_hindcast_disabled_when_offline(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    monkeypatch.delenv("NAVIGUIDE_HINDCAST", raising=False)
    monkeypatch.delenv("NAVIGUIDE_FORECAST_BACKEND", raising=False)
    import hindcast
    assert hindcast.hindcast_enabled() is False


def test_tavily_returns_empty_when_offline(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    monkeypatch.setenv("TAVILY_API_KEY", "fake-should-not-be-used")
    import asyncio
    import tavily_client

    empty = asyncio.run(tavily_client.extract(["https://example.com/page"]))
    assert empty["text"] == ""
    assert empty["results"] == []


def test_fill_dossier_offline_is_empty_without_http(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    import asyncio
    import ici_engine

    bag = asyncio.run(ici_engine.fill_dossier(46.15, -1.16, thin=True))
    assert bag.get("status") == "unavailable"
    assert bag.get("reason") == "hors ligne"
