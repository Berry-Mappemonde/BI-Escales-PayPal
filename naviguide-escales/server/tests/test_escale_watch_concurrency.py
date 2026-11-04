"""Veille Tavily en concurrence : les plafonds tiennent (PR #25, Review Bot).

GET /escale lance une tâche par slug ; la boucle du jour passe aussi. Faux
Tavily seulement (aucun réseau) : la recherche attend un tour de boucle,
comme un vrai appel HTTP, pour que les tâches se chevauchent.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

import escale_api
import escale_watch
import llm_budget
import tavily_client

HIT = {
    "title": "Avis aux navigateurs",
    "url": "https://www.portautonome.nc/avis",
    "content": "Travaux annoncés à la marina de Motu Uta.",
}
NAMES = ["Nouméa", "Ajaccio", "Brisbane", "La Rochelle", "Fort-de-France",
         "San Francisco", "Papeete", "Suva"]
_RealAsyncClient = httpx.AsyncClient


def _keys(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    monkeypatch.delenv("NAVIGUIDE_OFFLINE", raising=False)
    # Pas de LLM : le résumé retombe sur la phrase de règles, un tour par escale.
    for k in ("NEBIUS_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _fake_tavily(monkeypatch, seen):
    """Le vrai tavily_client.search (crédits comptés), un faux transport HTTP lent."""

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/search"):
            seen.append(request.read().decode())
            await asyncio.sleep(0.02)
            return httpx.Response(200, json={"results": [HIT]})
        return httpx.Response(404, json={"detail": url})

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return _RealAsyncClient(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tavily_client, "httpx", SimpleNamespace(AsyncClient=client))


def _stop(name, arrival):
    return {"name": name, "slug": escale_watch.slug(name), "arrival": arrival,
            "lat": -22.27, "lon": 166.44, "url": None}


def _official_window(monkeypatch, arrival):
    def fake(name, now=None, *, lat=None, lon=None):
        return _stop(name, arrival)

    monkeypatch.setattr(escale_watch, "official_stop_in_window", fake)


async def _drain():
    for _ in range(200):
        pending = [t for t in escale_api._WATCH_TASKS if not t.done()]
        if not pending:
            return
        # wait() ne lit pas les exceptions : c'est au rappel de la tâche de le faire.
        await asyncio.wait(pending)


def _get_many(names):
    async def run():
        for n in names:
            escale_api._schedule_escale_watch(n, -22.27, 166.44)
        await _drain()

    escale_api._INFLIGHT.clear()
    try:
        asyncio.run(run())
    finally:
        escale_api._INFLIGHT.clear()


def test_eight_simultaneous_gets_respect_daily_search_cap(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_WATCH_DAILY_SEARCHES", "6")
    seen: list = []
    _fake_tavily(monkeypatch, seen)
    _official_window(monkeypatch, datetime.now(timezone.utc) + timedelta(days=3))

    _get_many(NAMES)

    assert len(seen) == 6
    assert escale_watch._watch_search_count() == 6
    assert llm_budget.tavily_usage()["credits"] == 6


def test_five_simultaneous_gets_respect_credit_cap(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_DAILY_CREDITS", "3")
    seen: list = []
    _fake_tavily(monkeypatch, seen)
    _official_window(monkeypatch, datetime.now(timezone.utc) + timedelta(days=3))

    _get_many(NAMES[:5])

    assert llm_budget.tavily_usage()["credits"] <= 3
    assert len(seen) <= 3
    assert llm_budget.allow_tavily() is False


def test_daily_loop_and_get_on_same_stop_search_once(monkeypatch):
    _keys(monkeypatch)
    seen: list = []
    _fake_tavily(monkeypatch, seen)
    now = datetime.now(timezone.utc)
    arrival = now + timedelta(days=3)
    _official_window(monkeypatch, arrival)
    voy = {"clock": {
        "t0": "2026-01-01T00:00:00Z",
        "marks": [{"name": "Nouméa", "iso": arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "lat": -22.27, "lon": 166.44}],
    }}

    async def run():
        loop_pass = asyncio.ensure_future(escale_watch.run_daily_watch(voy, now))
        escale_api._schedule_escale_watch("Nouméa", -22.27, 166.44)
        out = await loop_pass
        await _drain()
        return out

    escale_api._INFLIGHT.clear()
    try:
        asyncio.run(run())
    finally:
        escale_api._INFLIGHT.clear()

    assert len(seen) == 1
    assert llm_budget.tavily_usage()["credits"] == 1
    assert escale_watch.watch_done("Nouméa")


def test_failed_get_watch_task_is_logged_and_released(monkeypatch, caplog):
    _keys(monkeypatch)
    _official_window(monkeypatch, datetime.now(timezone.utc) + timedelta(days=3))

    async def boom(stop, now, **kwargs):
        await asyncio.sleep(0)
        raise RuntimeError("tavily en panne")

    monkeypatch.setattr(escale_watch, "watch_stop", boom)
    async def run():
        escale_api._schedule_escale_watch("Nouméa", -22.27, 166.44)
        assert "noumea" in escale_api._INFLIGHT
        await _drain()
        await asyncio.sleep(0)

    escale_api._INFLIGHT.clear()
    caplog.set_level(logging.WARNING, logger="naviguide-simulator.escale")
    try:
        asyncio.run(run())
        assert "noumea" not in escale_api._INFLIGHT
    finally:
        escale_api._INFLIGHT.clear()
    assert any("tavily en panne" in r.getMessage() for r in caplog.records)
    assert not any("never retrieved" in r.getMessage() for r in caplog.records)


def test_timeouts_on_repeated_gets_stay_under_daily_search_cap(monkeypatch, caplog):
    """Tavily qui répond toujours par un timeout : chaque échec libère le slug,
    mais le plafond de recherches du jour borne aussi les tentatives."""
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_WATCH_DAILY_SEARCHES", "6")
    monkeypatch.setenv("NAVIGUIDE_TAVILY_DAILY_CREDITS", "1000")
    _official_window(monkeypatch, datetime.now(timezone.utc) + timedelta(days=3))
    seen: list = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/search"):
            seen.append(request.read().decode())
            await asyncio.sleep(0)
            raise httpx.ReadTimeout("lecture trop longue", request=request)
        return httpx.Response(404, json={"detail": str(request.url)})

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return _RealAsyncClient(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tavily_client, "httpx", SimpleNamespace(AsyncClient=client))
    caplog.set_level(logging.WARNING, logger="naviguide-simulator.escale")

    async def run():
        for _ in range(30):
            escale_api._schedule_escale_watch("Nouméa", -22.27, 166.44)
            await _drain()
            await asyncio.sleep(0)

    escale_api._INFLIGHT.clear()
    try:
        asyncio.run(run())
    finally:
        escale_api._INFLIGHT.clear()

    assert 1 <= len(seen) <= 6
    assert escale_watch._watch_search_count() <= 6
    assert escale_watch._watch_search_count() == len(seen)
    # Requête partie puis timeout : Tavily l'a sans doute facturée.
    assert llm_budget.tavily_usage()["credits"] == len(seen)
    assert not escale_watch.watch_done("Nouméa")
