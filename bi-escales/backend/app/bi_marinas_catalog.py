"""Live Blue Intelligence marina lookups for Escales stopover sheets.

Fetch pattern adapted from ``app/bi_projects_catalog.py`` (PR #55): 15-minute
in-memory cache, last-good backup, bundled/local fallback for the escale slice only.

When ``BI_MARINAS_ENRICH_URL`` is set, enrichment rows are fetched from the
Blue Intelligence public endpoint (Part A). Otherwise the server indexes the
public ``/export/marinas.geojson`` export (never sent to the browser whole).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from app.marina_place_link import apply_maps_place_policy
from app.bi_projects_catalog import ACCEPT, DEFAULT_BI_API, bi_api_base

CACHE_TTL = 900.0
DEFAULT_MARINAS_EXPORT = f"{DEFAULT_BI_API}/export/marinas.geojson"

ENRICH_FIELD_KEYS = (
    "canal_vhf",
    "places_visiteurs",
    "tirant_eau_max_metres",
    "score_protection_meteo",
    "services_disponibles",
    "telephone_capitainerie",
    "resume_avis",
)

# Read-only projection — Blue-Intelligence-V3 ``export_marina_fiches`` (routers/marinas.py).
MARINAS_MONGO_PROJECTION = {
    "osm_id": 1,
    "name": 1,
    "lat": 1,
    "lon": 1,
    "website": 1,
    "maps_place_url": 1,
    **{field: 1 for field in ENRICH_FIELD_KEYS},
}

DEFAULT_BI_MARINAS_DB = "blueintel_db"

_BUNDLED_ESCALE = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "escale-marinas.json"
)

_export_cache: dict[str, Any] = {"at": 0.0, "index": None}
_export_last_good: Optional[dict[str, dict[str, Any]]] = None

_stop_marinas_cache: dict[str, dict[str, Any]] = {}
_stop_marinas_last_good: dict[str, list[dict[str, Any]]] = {}

_bi_marinas_mongo_client: Optional[Any] = None


def reset_bi_marinas_cache() -> None:
    """Test helper: drop export index cache."""
    global _export_last_good, _bi_marinas_mongo_client
    _export_cache["at"] = 0.0
    _export_cache["index"] = None
    _export_last_good = None
    _stop_marinas_cache.clear()
    _stop_marinas_last_good.clear()
    client = _bi_marinas_mongo_client
    _bi_marinas_mongo_client = None
    if client is not None:
        client.close()


def bi_marinas_mongo_uri() -> str:
    return (os.getenv("BI_MARINAS_MONGODB_URI") or "").strip()


def bi_marinas_mongo_db_name() -> str:
    raw = (os.getenv("BI_MARINAS_MONGODB_DB_NAME") or DEFAULT_BI_MARINAS_DB).strip()
    return raw or DEFAULT_BI_MARINAS_DB


def reset_bi_marinas_mongo_client() -> None:
    """Test helper: close the Atlas read client."""
    global _bi_marinas_mongo_client
    client = _bi_marinas_mongo_client
    _bi_marinas_mongo_client = None
    if client is not None:
        client.close()


def get_bi_marinas_mongo_client() -> Any:
    """Motor client for ``blueintel_db.marinas`` (separate from Escales ``MONGO_URL``)."""
    global _bi_marinas_mongo_client
    if _bi_marinas_mongo_client is None:
        uri = bi_marinas_mongo_uri()
        if not uri:
            raise RuntimeError("BI_MARINAS_MONGODB_URI is not set")
        from motor.motor_asyncio import AsyncIOMotorClient

        _bi_marinas_mongo_client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=20_000,
            connectTimeoutMS=20_000,
            socketTimeoutMS=300_000,
            maxPoolSize=10,
            retryWrites=False,
        )
    return _bi_marinas_mongo_client


def marinas_enrich_api_url() -> str | None:
    raw = (os.getenv("BI_MARINAS_ENRICH_URL") or "").strip()
    return raw.rstrip("/") if raw else None


def _marinas_export_urls() -> list[str]:
    base = bi_api_base()
    urls = [f"{base}/export/marinas.geojson", DEFAULT_MARINAS_EXPORT]
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def load_bundled_escale_snapshot() -> dict[str, Any]:
    return json.loads(_BUNDLED_ESCALE.read_text(encoding="utf-8"))


def bundled_escale_entry(stop_name: str) -> dict[str, Any]:
    snapshot = load_bundled_escale_snapshot()
    row = (snapshot.get("escales") or {}).get(stop_name)
    if not isinstance(row, dict):
        return {"name": stop_name, "sections": {}}
    return json.loads(json.dumps(row))


def _services_from_export_props(props: dict[str, Any]) -> list[str] | None:
    direct = props.get("services_disponibles")
    if isinstance(direct, list) and direct:
        return [str(x) for x in direct if str(x).strip()]
    svc = props.get("svc")
    if not isinstance(svc, dict):
        return None
    labels: list[str] = []
    for bucket in svc.values():
        if isinstance(bucket, list):
            for item in bucket:
                text = str(item).strip()
                if text and text not in labels:
                    labels.append(text)
        if len(labels) >= 12:
            break
    return labels or None


def enrichment_from_props(props: dict[str, Any]) -> dict[str, Any]:
    """Normalize BI export or Part-A JSON row into merge fields."""
    out: dict[str, Any] = {}
    website = props.get("website")
    if website:
        out["website"] = str(website).strip()
    maps_place = props.get("maps_place_url") or props.get("maps_url")
    if maps_place:
        out["maps_url"] = str(maps_place).strip()
    phone = props.get("telephone_capitainerie") or props.get("phone")
    if phone:
        out["phone"] = str(phone).strip()
    services = _services_from_export_props(props)
    if services:
        out["services"] = services
    for key in ENRICH_FIELD_KEYS:
        val = props.get(key)
        if val not in (None, "", [], {}):
            out[key] = val
    return out


def enrichment_from_mongo_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Map a ``blueintel_db.marinas`` row into ``merge_marina_row`` enrichment."""
    props = dict(doc)
    if doc.get("maps_place_url") and not props.get("maps_url"):
        props["maps_place_url"] = doc["maps_place_url"]
    return enrichment_from_props(props)


def mooring_marinas_to_geojson(marinas: list[dict[str, Any]]) -> dict[str, Any]:
    """FeatureCollection for the map and Marinas panel (mirrors ``marinasToFeatures.js``)."""
    features: list[dict[str, Any]] = []
    for index, row in enumerate(marinas or []):
        if not isinstance(row, dict):
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if lat != lat or lon != lon:
            continue
        osm_id = str(row.get("osm_id") or "").strip()
        name = row.get("name")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "id": osm_id or str(name or index),
                    "name": name,
                    "osm_id": osm_id,
                    "website": row.get("url") or row.get("visit_url") or "",
                    "maps_url": row.get("maps_url"),
                    "safe_google_place": bool(row.get("safe_google_place")),
                    "nm": row.get("nm"),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


async def fetch_mongo_marina_docs(osm_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Read-only ``find`` on ``blueintel_db.marinas`` with a fixed projection."""
    ids = [str(x).strip() for x in osm_ids if str(x).strip()]
    if not ids or not bi_marinas_mongo_uri():
        return {}
    client = get_bi_marinas_mongo_client()
    coll = client[bi_marinas_mongo_db_name()]["marinas"]
    cursor = coll.find({"osm_id": {"$in": ids}}, MARINAS_MONGO_PROJECTION)
    docs = await cursor.to_list(length=len(ids))
    return {str(d.get("osm_id")): d for d in docs if d.get("osm_id")}


async def merge_stopover_mooring_marinas(
    stop_name: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Bundled escale list enriched from Mongo (preferred) or BI HTTP export."""
    base = bundled_escale_entry(stop_name)
    marinas = (
        (base.get("sections") or {})
        .get("mooring", {})
        .get("marinas")
    )
    if not isinstance(marinas, list) or not marinas:
        return []

    osm_ids = [str(m.get("osm_id") or "").strip() for m in marinas if m.get("osm_id")]
    enrichments: dict[str, dict[str, Any]] = {}
    if bi_marinas_mongo_uri() and osm_ids:
        try:
            docs = await fetch_mongo_marina_docs(osm_ids)
            enrichments = {
                oid: enrichment_from_mongo_doc(docs[oid]) for oid in osm_ids if oid in docs
            }
        except Exception:
            enrichments = {}
    if not enrichments and osm_ids:
        try:
            enrichments = await lookup_marina_enrichments(osm_ids, client=client)
        except Exception:
            enrichments = {}

    merged: list[dict[str, Any]] = []
    for marina in marinas:
        if not isinstance(marina, dict):
            continue
        oid = str(marina.get("osm_id") or "").strip()
        merged.append(merge_marina_row(marina, enrichments.get(oid)))
    return merged


async def get_escale_marinas_geojson(
    stop_name: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Cached mooring marinas for one stop (live Mongo → last good → bundled only)."""
    name = (stop_name or "").strip()
    if not name:
        return {"type": "FeatureCollection", "features": []}

    now = time.monotonic()
    cached = _stop_marinas_cache.get(name)
    if cached and now - float(cached.get("at") or 0) < CACHE_TTL:
        return cached["payload"]

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        rows = await merge_stopover_mooring_marinas(name, client=client)
        payload = mooring_marinas_to_geojson(rows)
        _stop_marinas_last_good[name] = rows
        _stop_marinas_cache[name] = {"at": now, "payload": payload}
        return payload
    except Exception:
        if name in _stop_marinas_last_good:
            payload = mooring_marinas_to_geojson(_stop_marinas_last_good[name])
            _stop_marinas_cache[name] = {"at": now, "payload": payload}
            return payload
        rows = []
        base = bundled_escale_entry(name)
        raw = (base.get("sections") or {}).get("mooring", {}).get("marinas") or []
        for marina in raw:
            if isinstance(marina, dict):
                rows.append(merge_marina_row(marina, None))
        payload = mooring_marinas_to_geojson(rows)
        _stop_marinas_cache[name] = {"at": now, "payload": payload}
        return payload
    finally:
        if owns_client:
            await client.aclose()


def merge_marina_row(base: dict[str, Any], enrichment: dict[str, Any] | None) -> dict[str, Any]:
    """Same public shape as naviguide ``_slim`` mooring items + enrich fields."""
    keep = ("name", "lat", "lon", "nm", "url", "visit_url", "phone", "type", "kind", "source", "osm_id")
    out = {k: base[k] for k in keep if k in base and base[k] is not None}
    if not enrichment:
        return apply_maps_place_policy(out)
    if not out.get("url") and enrichment.get("website"):
        out["url"] = enrichment["website"]
    if enrichment.get("maps_url"):
        out["maps_url"] = enrichment["maps_url"]
    if not out.get("phone") and enrichment.get("phone"):
        out["phone"] = enrichment["phone"]
    if enrichment.get("services"):
        out["services"] = enrichment["services"]
    for key in ENRICH_FIELD_KEYS:
        if enrichment.get(key) not in (None, "", [], {}):
            out[key] = enrichment[key]
    return apply_maps_place_policy(out)


def _index_features(features: list[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for raw in features or []:
        if not isinstance(raw, dict):
            continue
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        osm_id = str(props.get("osm_id") or "").strip()
        if osm_id:
            index[osm_id] = props
    return index


async def _fetch_export_index(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    last_error: Exception | None = None
    for url in _marinas_export_urls():
        try:
            response = await client.get(url, headers={"Accept": ACCEPT})
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(features, list):
                raise ValueError("invalid GeoJSON FeatureCollection")
            return _index_features(features)
        except Exception as exc:  # noqa: BLE001 — try fallback URL
            last_error = exc
            continue
    raise RuntimeError("BI marinas export unavailable") from last_error


async def get_marinas_export_index(
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, dict[str, Any]]:
    """Cached osm_id → export properties (server-side only)."""
    global _export_last_good
    now = time.monotonic()
    cached = _export_cache.get("index")
    if isinstance(cached, dict) and now - float(_export_cache.get("at") or 0) < CACHE_TTL:
        return cached

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        index = await _fetch_export_index(client)
        _export_last_good = index
        _export_cache["at"] = now
        _export_cache["index"] = index
        return index
    except Exception:
        if _export_last_good:
            _export_cache["at"] = now
            _export_cache["index"] = _export_last_good
            return _export_last_good
        raise
    finally:
        if owns_client:
            await client.aclose()


async def _fetch_enrich_api_rows(
    client: httpx.AsyncClient,
    osm_ids: list[str],
) -> dict[str, dict[str, Any]]:
    base = marinas_enrich_api_url()
    if not base or not osm_ids:
        return {}
    params: list[tuple[str, str]] = [("limit", str(min(len(osm_ids), 200)))]
    for oid in osm_ids:
        params.append(("osm_id", oid))
    response = await client.get(base, params=params, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("invalid marinas enrich payload")
    out: dict[str, dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("osm_id") or "").strip()
        if oid:
            out[oid] = row
    return out


async def lookup_marina_enrichments(
    osm_ids: list[str],
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, dict[str, Any]]:
    """Return osm_id → normalized enrichment dict."""
    ids = [str(x).strip() for x in osm_ids if str(x).strip()]
    if not ids:
        return {}

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        if bi_marinas_mongo_uri():
            try:
                docs = await fetch_mongo_marina_docs(ids)
                if docs:
                    return {
                        oid: enrichment_from_mongo_doc(docs[oid])
                        for oid in ids
                        if oid in docs
                    }
            except Exception:
                pass

        if marinas_enrich_api_url():
            rows = await _fetch_enrich_api_rows(client, ids)
            return {oid: enrichment_from_props(rows[oid]) for oid in ids if oid in rows}

        index = await get_marinas_export_index(client)
        return {
            oid: enrichment_from_props(index[oid])
            for oid in ids
            if oid in index
        }
    finally:
        if owns_client:
            await client.aclose()


async def build_escale_fiche(stop_name: str) -> dict[str, Any]:
    """Enrich bundled escale marinas by osm_id; fall back to local snapshot."""
    base = bundled_escale_entry(stop_name)
    marinas = (
        (base.get("sections") or {})
        .get("mooring", {})
        .get("marinas")
    )
    if not isinstance(marinas, list) or not marinas:
        return base

    try:
        merged = await merge_stopover_mooring_marinas(stop_name)
    except Exception:
        merged = [
            merge_marina_row(m, None)
            for m in marinas
            if isinstance(m, dict)
        ]

    out = json.loads(json.dumps(base))
    out.setdefault("sections", {}).setdefault("mooring", {})["marinas"] = merged
    return out
