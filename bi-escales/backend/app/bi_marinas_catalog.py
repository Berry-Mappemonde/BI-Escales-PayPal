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

_BUNDLED_ESCALE = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "escale-marinas.json"
)

_export_cache: dict[str, Any] = {"at": 0.0, "index": None}
_export_last_good: Optional[dict[str, dict[str, Any]]] = None


def reset_bi_marinas_cache() -> None:
    """Test helper: drop export index cache."""
    global _export_last_good
    _export_cache["at"] = 0.0
    _export_cache["index"] = None
    _export_last_good = None


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


def merge_marina_row(base: dict[str, Any], enrichment: dict[str, Any] | None) -> dict[str, Any]:
    """Same public shape as naviguide ``_slim`` mooring items + enrich fields."""
    keep = ("name", "lat", "lon", "nm", "url", "visit_url", "phone", "type", "kind", "source")
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

    osm_ids = [str(m.get("osm_id") or "").strip() for m in marinas if m.get("osm_id")]
    enrichments: dict[str, dict[str, Any]] = {}
    try:
        enrichments = await lookup_marina_enrichments(osm_ids)
    except Exception:
        enrichments = {}

    merged = []
    for marina in marinas:
        if not isinstance(marina, dict):
            continue
        oid = str(marina.get("osm_id") or "").strip()
        merged.append(merge_marina_row(marina, enrichments.get(oid)))

    out = json.loads(json.dumps(base))
    out.setdefault("sections", {}).setdefault("mooring", {})["marinas"] = merged
    return out
