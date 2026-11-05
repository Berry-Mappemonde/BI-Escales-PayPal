"""Live BI marina enrichment for escale sheets."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bi_marinas_catalog import (
    build_escale_fiche,
    bundled_escale_entry,
    enrichment_from_props,
    get_marinas_export_index,
    lookup_marina_enrichments,
    merge_marina_row,
    reset_bi_marinas_cache,
)
from app.main import app
from fastapi.testclient import TestClient


def _export_feature(osm_id: str, **extra: object) -> dict:
    props = {
        "osm_id": osm_id,
        "name": "Test Marina",
        "website": "https://marina.example",
        "maps_place_url": "https://www.google.com/maps/place/Test",
        **extra,
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1.0, 46.0]},
        "properties": props,
    }


def test_merge_prefers_base_url_then_enrichment():
    base = {"name": "Minimes", "lat": 1.0, "lon": 2.0, "nm": 0.4, "url": "https://keep.me"}
    enrich = enrichment_from_props(
        {
            "website": "https://other.example",
            "maps_place_url": "https://maps.example/place",
            "telephone_capitainerie": "+33 1 23 45 67 89",
            "canal_vhf": "9",
            "services_disponibles": ["eau", "électricité"],
        }
    )
    row = merge_marina_row(base, enrich)
    assert row["url"] == "https://keep.me"
    assert row["maps_url"] == "https://maps.example/place"
    assert row["phone"] == "+33 1 23 45 67 89"
    assert row["canal_vhf"] == "9"
    assert row["services"] == ["eau", "électricité"]


def test_export_index_cache(monkeypatch):
    reset_bi_marinas_cache()
    monkeypatch.delenv("BI_MARINAS_ENRICH_URL", raising=False)
    monkeypatch.setenv("BI_API_URL", "https://bi.example/api")
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [_export_feature("way/1")]},
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await get_marinas_export_index(client)
            second = await get_marinas_export_index(client)
            return first, second

    first, second = asyncio.run(run())
    assert state["n"] == 1
    assert "way/1" in first
    assert first == second


def test_enrich_api_used_when_configured(monkeypatch):
    reset_bi_marinas_cache()
    monkeypatch.setenv("BI_MARINAS_ENRICH_URL", "https://bi.example/api/export/marinas-enriched.json")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "marinas-enriched" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "attribution": "© OpenStreetMap contributors (ODbL)",
                    "items": [
                        {
                            "osm_id": "way/741789648",
                            "website": "https://live.example",
                            "maps_place_url": "https://maps.example/live",
                            "canal_vhf": "12",
                        }
                    ],
                },
            )
        return httpx.Response(503)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await lookup_marina_enrichments(["way/741789648"], client)

    out = asyncio.run(run())
    assert any("marinas-enriched" in url for url in calls)
    assert out["way/741789648"]["canal_vhf"] == "12"


def test_build_escale_fiche_falls_back_to_local(monkeypatch):
    reset_bi_marinas_cache()

    async def boom(_ids, client=None):
        raise RuntimeError("down")

    monkeypatch.setattr("app.bi_marinas_catalog.lookup_marina_enrichments", boom)
    body = asyncio.run(build_escale_fiche("La Rochelle"))
    local = bundled_escale_entry("La Rochelle")
    assert body["name"] == "La Rochelle"
    assert len(body["sections"]["mooring"]["marinas"]) == len(local["sections"]["mooring"]["marinas"])


def test_build_escale_fiche_merges_export(monkeypatch):
    reset_bi_marinas_cache()
    monkeypatch.delenv("BI_MARINAS_ENRICH_URL", raising=False)

    async def fake_lookup(osm_ids, client=None):
        return {
            "way/741789648": enrichment_from_props(
                {
                    "website": "https://merged.example",
                    "maps_place_url": "https://maps.example/merged",
                    "canal_vhf": "9",
                    "places_visiteurs": 12,
                }
            )
        }

    monkeypatch.setattr("app.bi_marinas_catalog.lookup_marina_enrichments", fake_lookup)
    body = asyncio.run(build_escale_fiche("La Rochelle"))
    minimes = next(
        m for m in body["sections"]["mooring"]["marinas"] if m["name"] == "Port des Minimes"
    )
    assert minimes["url"] == "https://portlarochelle.com"
    assert minimes["maps_url"] == "https://maps.example/merged"
    assert minimes["canal_vhf"] == "9"
    assert minimes["places_visiteurs"] == 12
    assert "osm_id" not in minimes


def test_main_escale_fiche_route(monkeypatch):
    async def fake_build(name: str):
        return {"name": name, "sections": {"mooring": {"marinas": [{"name": "A", "nm": 0.1}]}}}

    import app.main as main

    monkeypatch.setattr(main, "build_escale_fiche", fake_build)
    client = TestClient(app)
    res = client.get("/api/escale-fiche", params={"name": "Dakar"})
    assert res.status_code == 200
    assert res.json()["sections"]["mooring"]["marinas"][0]["name"] == "A"
