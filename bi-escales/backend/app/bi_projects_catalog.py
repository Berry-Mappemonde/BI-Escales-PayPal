"""Live Blue Intelligence projects GeoJSON for the Escales map.

Fetch pattern adapted from ``naviguide-escales/server/main.py``
(``_fetch_catalog_features`` for the ``projects`` catalog → ``/export/geojson``).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .gear_projects_catalog import merge_gear_properties

DESCRIPTION_MAX = 160
CACHE_TTL = 900.0  # 15 minutes — same as NAVIGUIDE _CATALOG_SOURCE_TTL
DEFAULT_BI_API = "https://www.blueintelligence.online/api"
ACCEPT = "application/geo+json, application/json"

_BUNDLED = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "bi-projects.geojson"
)

_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_last_good: Optional[dict[str, Any]] = None


def reset_bi_projects_cache() -> None:
    """Test helper: drop in-memory cache and last-good copy."""
    global _last_good
    _cache["at"] = 0.0
    _cache["payload"] = None
    _last_good = None


def bi_api_base() -> str:
    raw = (os.getenv("BI_API_URL") or "").strip()
    return raw.rstrip("/") if raw else DEFAULT_BI_API


def _project_source_urls() -> list[str]:
    base = bi_api_base()
    urls = [f"{base}/export/geojson", f"{DEFAULT_BI_API}/projects"]
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _truncate_description(text: Any) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= DESCRIPTION_MAX:
        return cleaned
    return cleaned[:DESCRIPTION_MAX]


def _normalize_feature(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    geometry = raw.get("geometry")
    if not isinstance(geometry, dict):
        return None
    props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    project_id = str(props.get("id") or "").strip()
    if not project_id:
        return None
    category = props.get("category_group") or props.get("category") or "Other"
    base_props = {
        "id": project_id,
        "title": str(props.get("title") or ""),
        "funder": str(props.get("funder") or ""),
        "url": str(props.get("url") or ""),
        "category_group": str(category),
        "location": str(props.get("location") or ""),
        "description": _truncate_description(props.get("description")),
    }
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": merge_gear_properties({**props, **base_props}),
    }


def normalize_projects_collection(features: list[Any]) -> dict[str, Any]:
    """Same FeatureCollection shape as ``frontend/public/bi-projects.geojson``."""
    kept: list[dict[str, Any]] = []
    for item in features or []:
        normalized = _normalize_feature(item)
        if normalized:
            kept.append(normalized)
    return {"type": "FeatureCollection", "name": "BI projects snapshot", "features": kept}


def load_bundled_projects() -> dict[str, Any]:
    return json.loads(_BUNDLED.read_text(encoding="utf-8"))


async def _fetch_catalog_features(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Read BI projects export; no user-supplied URL is proxied."""
    last_error: Exception | None = None
    for url in _project_source_urls():
        try:
            response = await client.get(url, headers={"Accept": ACCEPT})
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(features, list):
                raise ValueError("invalid GeoJSON FeatureCollection")
            return features
        except Exception as exc:  # noqa: BLE001 — try fallback URL
            last_error = exc
            continue
    raise RuntimeError("BI projects export unavailable") from last_error


async def fetch_live_projects_collection(client: httpx.AsyncClient) -> dict[str, Any]:
    features = await _fetch_catalog_features(client)
    return normalize_projects_collection(features)


async def get_bi_projects_geojson(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Return cached live projects, else last good, else bundled snapshot."""
    global _last_good
    now = time.monotonic()
    cached = _cache.get("payload")
    if cached and now - float(_cache.get("at") or 0) < CACHE_TTL:
        return cached

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        payload = await fetch_live_projects_collection(client)
        _last_good = payload
        _cache["at"] = now
        _cache["payload"] = payload
        return payload
    except Exception:
        if _last_good:
            _cache["at"] = now
            _cache["payload"] = _last_good
            return _last_good
        bundled = load_bundled_projects()
        _cache["at"] = now
        _cache["payload"] = bundled
        return bundled
    finally:
        if owns_client:
            await client.aclose()
