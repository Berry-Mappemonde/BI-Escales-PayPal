"""Live BI projects GeoJSON route and cache."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bi_projects_catalog import (
    DESCRIPTION_MAX,
    get_bi_projects_geojson,
    load_bundled_projects,
    normalize_projects_collection,
    reset_bi_projects_cache,
)
from app.main import app
from fastapi.testclient import TestClient


def _feature(desc: str = "x" * 200) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        "properties": {
            "id": "proj-live-1",
            "title": "Live project",
            "funder": "Funder",
            "url": "https://example.org/p",
            "category_group": "Restoration",
            "location": "Ocean",
            "description": desc,
        },
    }


def test_normalize_truncates_description_to_160():
    row = normalize_projects_collection([_feature("a" * 250)])["features"][0]
    assert len(row["properties"]["description"]) == DESCRIPTION_MAX
    assert set(row["properties"]) == {
        "id",
        "title",
        "funder",
        "url",
        "category_group",
        "location",
        "description",
    }


def test_fetch_success(monkeypatch):
    reset_bi_projects_cache()
    monkeypatch.setenv("BI_API_URL", "https://bi.example/api")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [_feature("short")]},
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await get_bi_projects_geojson(client)

    body = asyncio.run(run())
    assert calls == ["https://bi.example/api/export/geojson"]
    assert body["features"][0]["properties"]["id"] == "proj-live-1"


def test_cache_hit_on_second_request(monkeypatch):
    reset_bi_projects_cache()
    monkeypatch.setenv("BI_API_URL", "https://bi.example/api")
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [_feature()]},
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await get_bi_projects_geojson(client)
            second = await get_bi_projects_geojson(client)
            return first, second

    first, second = asyncio.run(run())
    assert state["n"] == 1
    assert first == second


def test_bi_down_serves_last_good(monkeypatch):
    reset_bi_projects_cache()
    monkeypatch.setenv("BI_API_URL", "https://bi.example/api")
    state = {"n": 0, "fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["fail"]:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [_feature("good")]},
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            live = await get_bi_projects_geojson(client)
            from app import bi_projects_catalog as mod

            mod._cache["at"] = 0.0
            mod._cache["payload"] = None
            state["fail"] = True
            stale = await get_bi_projects_geojson(client)
            return live, stale

    live, stale = asyncio.run(run())
    assert state["n"] >= 2
    assert live["features"][0]["properties"]["description"] == "good"
    assert stale == live


def test_bi_down_without_last_good_uses_bundled_snapshot(monkeypatch):
    reset_bi_projects_cache()
    monkeypatch.delenv("BI_API_URL", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    bundled = load_bundled_projects()

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await get_bi_projects_geojson(client)

    body = asyncio.run(run())
    assert len(body["features"]) == len(bundled["features"])
    assert body["features"][0]["properties"]["id"] == bundled["features"][0]["properties"]["id"]


def test_main_exposes_bi_projects_route(monkeypatch):
    reset_bi_projects_cache()
    import app.main as main

    async def fake_geojson():
        return normalize_projects_collection([_feature("route")])

    monkeypatch.setattr(main, "get_bi_projects_geojson", fake_geojson)
    client = TestClient(app)
    response = client.get("/bi-projects.geojson")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["features"][0]["properties"]["id"] == "proj-live-1"
