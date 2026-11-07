"""Read-only ``blueintel_db.marinas`` route (Atlas URI, mocked collection)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bi_marinas_catalog as catalog
from app.bi_marinas_catalog import (
    MARINAS_MONGO_PROJECTION,
    get_escale_marinas_geojson,
    reset_bi_marinas_cache,
    reset_bi_marinas_mongo_client,
)
from app.main import app
from fastapi.testclient import TestClient

BAS_DU_FORT_OSM = "relation/5838544"
DRIVING_PLACE = (
    "https://www.google.com/maps/place/Auto+%C3%89cole+de+la+Pointe-%C3%A0-Pitre/"
    "@16.2510,-61.5480,17z"
)
MINIMES_PLACE = "https://www.google.com/maps/place/Port+des+Minimes/@46.1468,-1.1661,17z"


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    async def to_list(self, length: int | None = None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs
        self.find_calls: list[tuple[dict, dict]] = []

    def find(self, query: dict, projection: dict):
        self.find_calls.append((query, projection))
        wanted = set(query.get("osm_id", {}).get("$in") or [])
        matched = [d for d in self.docs if d.get("osm_id") in wanted]
        return _FakeCursor(matched)


class _FakeMongoClient:
    def __init__(self, collection: _FakeCollection):
        self._collection = collection

    def __getitem__(self, db_name: str):
        assert db_name == "blueintel_db"
        return {"marinas": self._collection}


@pytest.fixture
def mongo_env(monkeypatch):
    reset_bi_marinas_cache()
    reset_bi_marinas_mongo_client()
    monkeypatch.setenv("BI_MARINAS_MONGODB_URI", "mongodb://mock.example/blueintel")
    monkeypatch.delenv("BI_MARINAS_MONGODB_DB_NAME", raising=False)
    yield
    reset_bi_marinas_cache()
    reset_bi_marinas_mongo_client()


def test_fetch_uses_projection_only(mongo_env, monkeypatch):
    coll = _FakeCollection(
        [
            {
                "osm_id": "way/741789648",
                "name": "Port des Minimes",
                "lat": 46.1467598,
                "lon": -1.1660647,
                "maps_place_url": MINIMES_PLACE,
            }
        ]
    )
    monkeypatch.setattr(catalog, "get_bi_marinas_mongo_client", lambda: _FakeMongoClient(coll))

    docs = asyncio.run(catalog.fetch_mongo_marina_docs(["way/741789648"]))
    assert list(docs) == ["way/741789648"]
    assert coll.find_calls
    _query, projection = coll.find_calls[0]
    assert projection == MARINAS_MONGO_PROJECTION
    assert "_id" not in projection


def test_geojson_applies_safe_place_from_mongo(mongo_env, monkeypatch):
    coll = _FakeCollection(
        [
            {
                "osm_id": BAS_DU_FORT_OSM,
                "name": "Marina de Bas-du-Fort",
                "lat": 16.2203478,
                "lon": -61.5297219,
                "maps_place_url": DRIVING_PLACE,
            }
        ]
    )
    monkeypatch.setattr(catalog, "get_bi_marinas_mongo_client", lambda: _FakeMongoClient(coll))

    fc = asyncio.run(get_escale_marinas_geojson("Pointe-à-Pitre (Guadeloupe)"))
    bas = next(
        f
        for f in fc["features"]
        if f["properties"].get("name") == "Marina de Bas-du-Fort"
    )
    assert bas["properties"]["safe_google_place"] is False
    assert "/maps/search/" in bas["properties"]["maps_url"]


def test_bundled_fallback_when_uri_unset(monkeypatch):
    reset_bi_marinas_cache()
    monkeypatch.delenv("BI_MARINAS_MONGODB_URI", raising=False)
    fc = asyncio.run(get_escale_marinas_geojson("La Rochelle"))
    assert len(fc["features"]) >= 5
    assert all("geometry" in f for f in fc["features"])


def test_stop_cache_serves_last_good_on_merge_failure(mongo_env, monkeypatch):
    coll = _FakeCollection(
        [
            {
                "osm_id": "way/741789648",
                "name": "Port des Minimes",
                "lat": 46.1467598,
                "lon": -1.1660647,
                "maps_place_url": MINIMES_PLACE,
            }
        ]
    )
    monkeypatch.setattr(catalog, "get_bi_marinas_mongo_client", lambda: _FakeMongoClient(coll))

    asyncio.run(get_escale_marinas_geojson("La Rochelle"))
    catalog._stop_marinas_cache.clear()

    async def fail_merge(name: str, client=None):
        raise RuntimeError("live merge unavailable")

    monkeypatch.setattr(catalog, "merge_stopover_mooring_marinas", fail_merge)
    second = asyncio.run(get_escale_marinas_geojson("La Rochelle"))
    minimes = next(
        f for f in second["features"] if f["properties"].get("osm_id") == "way/741789648"
    )
    assert minimes["properties"]["safe_google_place"] is True


def test_main_exposes_escale_marinas_geojson(monkeypatch):
    reset_bi_marinas_cache()

    async def fake_geojson(name: str, client=None):
        return {"type": "FeatureCollection", "features": [{"type": "Feature"}]}

    import app.main as main

    monkeypatch.setattr(main, "get_escale_marinas_geojson", fake_geojson)
    client = TestClient(app)
    res = client.get("/api/escale-marinas.geojson", params={"name": "Dakar"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/geo+json")
