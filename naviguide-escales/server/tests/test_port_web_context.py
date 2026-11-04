"""Veille web Tavily pour le chat journal (port prochain)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

import llm_budget
import port_web_context
import tavily_client


def test_build_query_includes_port_and_region():
    q = port_web_context.build_query("Nouméa", "New Caledonia")
    assert "Nouméa" in q
    assert "New Caledonia" in q


def test_fetch_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = asyncio.run(port_web_context.fetch_port_web("La Rochelle"))
    assert out["status"] == "unavailable"
    assert out["reason"] == "no-key"
    assert llm_budget.tavily_usage()["calls"] == 0


def test_fetch_search_cached(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert "search" in str(request.url)
        body = json.loads(request.content.decode())
        assert "Nouméa" in body.get("query", "")
        return httpx.Response(200, json={
            "results": [{
                "title": "Port info",
                "url": "https://example.com/port",
                "content": "Travaux sur le quai.",
            }],
        })

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            a = await port_web_context.fetch_port_web("Nouméa", client=client)
            b = await port_web_context.fetch_port_web("Nouméa", client=client)
            return a, b

    first, second = asyncio.run(run())
    assert first["status"] == "ready"
    assert first["sources"][0]["url"] == "https://example.com/port"
    assert second["status"] == "ready"
    assert len(seen) == 1
    assert llm_budget.tavily_usage()["calls"] == 1


def test_fetch_distinguishes_http_error_from_empty_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if "HTTP-error" in request.content.decode():
            return httpx.Response(503, json={"results": []})
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            failed = await port_web_context.fetch_port_web("HTTP-error-port", client=client)
            empty = await port_web_context.fetch_port_web("Empty-port", client=client)
            return failed, empty

    failed, empty = asyncio.run(run())
    assert failed["status"] == "unavailable" and failed["reason"] == "http-error"
    assert empty["status"] == "unavailable" and empty["reason"] == "empty"


def test_attach_puts_port_web_on_context(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            ctx = {"nextStop": {"name": "Papeete"}}
            await port_web_context.attach(ctx, client, datetime.now(timezone.utc))
            return ctx

    ctx = asyncio.run(run())
    assert "portWeb" in ctx
    assert ctx["portWeb"]["status"] in {"ready", "unavailable"}


def test_pick_port_label_falls_back_to_nearest_named_port():
    from port_web_context import pick_port_label

    ctx = {"around": {"portsOfEntry": [], "ports": [{"name": "Lorient", "nm": 3.2}], "marinas": [{"name": "Kernevel"}]}}
    assert pick_port_label(ctx) == "Lorient"
    assert pick_port_label({"nextStop": {"name": "Mindelo"}, **ctx}) == "Mindelo"
    assert pick_port_label({"around": {"ports": [{"nm": 1}]}}) is None


def test_pick_port_label_prefers_port_like_name():
    from port_web_context import pick_port_label

    ctx = {"around": {"marinas": [{"name": "Technimarine"}, {"name": "Marina de Papeete"}]}}
    assert pick_port_label(ctx) == "Marina de Papeete"
    assert pick_port_label({"around": {"marinas": [{"name": "Technimarine"}]}}) == "Technimarine"


def test_region_hint_keeps_country_inside_parentheses():
    from port_web_context import pick_region_hint

    ctx = {"around": {"zee": {"name": "French Exclusive Economic Zone (French Polynesia)"}}}
    assert pick_region_hint(ctx) == "French Polynesia"
    assert pick_region_hint({"around": {"zee": {"name": "Irish EEZ"}}}) == "Irish EEZ"


def test_search_uses_general_topic_without_day_window(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await port_web_context.fetch_port_web("Papeete", region="French Polynesia", client=client)

    asyncio.run(run())
    assert bodies[0]["topic"] == "general"
    assert "days" not in bodies[0]
    assert bodies[0]["query"].startswith("Papeete French Polynesia")


def test_film_boat_uses_port_near_boat_not_official_next_stop():
    from port_web_context import pick_port_label

    ctx = {
        "nextStop": {"name": "Nouméa (Nouvelle-Calédonie)"},
        "boat": {"lat": -17.5, "lon": -149.6, "basis": "simulation"},
        "around": {"marinas": [{"name": "Marina de Papeete"}]},
    }
    assert pick_port_label(ctx) == "Marina de Papeete"
    ctx["boat"]["basis"] = "clock"
    assert pick_port_label(ctx) == "Nouméa (Nouvelle-Calédonie)"


def test_official_stop_query_has_no_boat_region(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = {
                "nextStop": {"name": "Nouméa"},
                "boat": {"basis": "clock"},
                "around": {"zee": {"name": "French Exclusive Economic Zone (French Polynesia)"}},
            }
            await port_web_context.attach(ctx, client, datetime.now(timezone.utc))

    asyncio.run(run())
    assert "Polynesia" not in bodies[0]["query"]
