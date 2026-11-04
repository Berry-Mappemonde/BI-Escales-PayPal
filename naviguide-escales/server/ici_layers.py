"""Familles hors dump carte pour le sac `ici()`.

Satellites (CDSE STAC), Open-Meteo / GRIB2, EMODnet au point,
AtoN (NOAA ENC + Overpass), mouillages OSM, Review/Gold.
Jamais d’invention : null + source/reason si le produit manque.
"""
from __future__ import annotations

import atexit
import asyncio
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from longitude import delta_lon, wrap_lon, wrap_lon_into

USER_AGENT = "NAVIGUIDE-simulator/0.2 (Berry-Mappemonde expedition)"

_EXC_TOKEN = re.compile(
    r"HTTPStatusError|Traceback|<class\b|\b(?:Exception|Error|Timeout\w*)\b"
)
_KNOWN_LAYER_DETAIL = {
    "rtofs_no_cycle", "rtofs_no_prog", "h5py_missing", "not_ingested",
    "no_data", "unavailable", "error", "no_scene_in_bbox",
}


def layer_code(prefix: str, detail: Any = None) -> str:
    """Stable layer reason. Exception class names become ``unavailable``; HTTP statuses stay."""
    if isinstance(detail, bool) or detail is None:
        text = ""
    else:
        text = str(detail).strip()
    text = re.sub(r"Traceback \(most recent call last\):[\s\S]*", "", text)
    text = re.sub(r"<class '[^']+'>", "", text).strip(" :")
    if re.fullmatch(r"\d{3}", text):
        return f"{prefix}:{text}" if prefix else text
    if text in _KNOWN_LAYER_DETAIL:
        return f"{prefix}:{text}" if prefix else text
    if not text or _EXC_TOKEN.search(text):
        suffix = "unavailable"
        return f"{prefix}:{suffix}" if prefix else suffix
    return f"{prefix}:{text}" if prefix else text

STAC_SEARCH = "https://stac.dataspace.copernicus.eu/v1/search"
STAC_COLLECTION = "sentinel-2-l2a"
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
    "/protocol/openid-connect/token"
)
COPERNICUS_BROWSER = "https://browser.dataspace.copernicus.eu/"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"
RTOFS_PROD = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtofs/prod/"
RTOFS_FILL = 1.0e20
RTOFS_PROG_NAMES = (
    "rtofs_glo_2ds_n000_prog.nc",
    "rtofs_glo_2ds_f000_prog.nc",
)
RTOFS_HYCOM_WEST = 74.0
RTOFS_HYCOM_EAST = 434.0
RTOFS_MS_TO_KN = 1.943844
EMODNET_DEPTH = "https://rest.emodnet-bathymetry.eu/depth_sample"
EMODNET_BATHY_WMS = "https://ows.emodnet-bathymetry.eu/wms"
EMODNET_SEABED_WMS = "https://drive.emodnet-geology.eu/geoserver/gtk/wms"
EMODNET_CABLES_WMS = "https://ows.emodnet-humanactivities.eu/wms"
OVERPASS_ENDPOINTS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

US_BBOXES: tuple[tuple[float, float, float, float], ...] = (
    (-125.0, 24.0, -66.0, 49.5),
    (-179.5, 51.0, -129.0, 72.0),
    (-160.5, 18.8, -154.5, 22.4),
    (-68.0, 17.8, -65.2, 18.6),
)

MAX_ATON = 8
MAX_SCENES = 1
_stac_token: dict[str, Any] = {"value": None, "ts": 0.0}
_TOKEN_TTL = 500.0

DERIVED_NULL = {
    "coastline": {
        "value": None,
        "source": "sentinel-pilot",
        "reason": "not_generated",
    },
    "sdb": {
        "value": None,
        "source": "sentinel-pilot",
        "reason": "not_generated",
    },
    "intertidal": {
        "value": None,
        "source": "sentinel-pilot",
        "reason": "not_generated",
    },
}


def absent(kind: str, source: str | None, reason: str) -> dict:
    return {
        "kind": kind,
        "source": source,
        "reason": reason,
        "value": None,
    }


def empty_satellites() -> dict:
    return {
        "kind": "observation",
        "source": None,
        "reason": None,
        "scene": None,
        "scenes": [],
        "bbox": None,
        "link": None,
        "url": STAC_SEARCH,
        "http_status": None,
        "derived": {k: dict(v) for k, v in DERIVED_NULL.items()},
    }


def empty_weather() -> dict:
    return {
        "kind": "forecast",
        "status": "absent",
        "refreshing": False,
        "source": None,
        "reason": None,
        "issued": None,
        "model": None,
        "cycle": None,
        "cell": None,
        "wind": None,
        "wave": None,
        "current": None,
        "current_reason": None,
    }


def empty_emodnet() -> dict:
    return {
        "kind": "observation",
        "source": "emodnet",
        "reason": None,
        "bathy": None,
        "seabed": None,
        "cables": None,
    }


def empty_aton() -> dict:
    return {
        "nearby": [],
        "source": None,
        "reason": None,
    }


def empty_review() -> dict:
    return {
        "zee": None,
        "amp": None,
        "source": None,
        "reason": None,
        "http_status": None,
        "url": None,
    }


def bbox_intersects_us(bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    for uw, us, ue, un in US_BBOXES:
        if west < ue and east > uw and south < un and north > us:
            return True
    return False


def scene_bbox(lat: float, lon: float, nm: float = 8.0) -> list[float]:
    dlat = nm / 60.0
    clat = max(0.2, abs(math.cos(math.radians(lat))))
    dlon = nm / (60.0 * clat)
    west = lon - dlon
    east = lon + dlon
    # STAC bbox must stay inside [-180, 180]; do not cross the antimeridian.
    west = max(-180.0, west)
    east = min(180.0, east)
    if west >= east:
        if lon >= 0:
            west, east = max(180.0 - max(0.05, dlon), -180.0), 180.0
        else:
            west, east = -180.0, min(-180.0 + max(0.05, dlon), 180.0)
    return [west, max(-90.0, lat - dlat), east, min(90.0, lat + dlat)]


def _browser_link(lat: float, lon: float, when: str | None = None) -> str:
    q = {
        "zoom": "11",
        "lat": f"{lat:.5f}",
        "lng": f"{lon:.5f}",
        "datasetId": "S2_L2A_CDAS",
    }
    if when:
        q["fromTime"] = when
        q["toTime"] = when
    return f"{COPERNICUS_BROWSER}?{urlencode(q)}"


def _stac_item_link(scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    return f"https://stac.dataspace.copernicus.eu/v1/collections/{STAC_COLLECTION}/items/{scene_id}"


async def _cdse_token(client: httpx.AsyncClient) -> str | None:
    now = time.time()
    if _stac_token["value"] and now - _stac_token["ts"] < _TOKEN_TTL:
        return _stac_token["value"]
    user = (os.getenv("CDSE_USERNAME") or "").strip()
    password = os.getenv("CDSE_PASSWORD") or ""
    if not user or not password:
        return None
    try:
        r = await client.post(
            CDSE_TOKEN_URL,
            data={
                "client_id": "cdse-public",
                "grant_type": "password",
                "username": user,
                "password": password,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=8.0,
        )
        r.raise_for_status()
        token = (r.json() or {}).get("access_token")
    except Exception:
        return None
    if not token:
        return None
    _stac_token["value"] = token
    _stac_token["ts"] = now
    return token


def slim_stac_scene(feat: dict, lat: float, lon: float) -> dict | None:
    if not isinstance(feat, dict):
        return None
    props = feat.get("properties") or {}
    scene_id = feat.get("id")
    when = props.get("datetime") or props.get("start_datetime")
    bbox = feat.get("bbox")
    links = feat.get("links") or []
    href = None
    for link in links:
        if isinstance(link, dict) and link.get("rel") in ("self", "canonical"):
            href = link.get("href")
            break
    href = href or _stac_item_link(scene_id)
    return {
        "kind": "observation",
        "product": (feat.get("collection") or STAC_COLLECTION),
        "id": scene_id,
        "datetime": when,
        "platform": props.get("platform") or props.get("constellation"),
        "cloud_cover": props.get("eo:cloud_cover"),
        "bbox": bbox,
        "link": href,
        "browser": _browser_link(lat, lon, when),
    }


async def fetch_satellite_scene(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
) -> dict:
    bag = empty_satellites()
    bbox = scene_bbox(lat, lon)
    bag["bbox"] = bbox
    bag["link"] = _browser_link(lat, lon)
    bag["url"] = STAC_SEARCH
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    attempts = (
        {"cloud": 40, "nm": 8.0, "start": "2025-01-01T00:00:00Z"},
        {"cloud": 80, "nm": 16.0, "start": "2024-01-01T00:00:00Z"},
        {"cloud": None, "nm": 30.0, "start": "2020-01-01T00:00:00Z"},
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json, application/json",
        "Content-Type": "application/json",
    }
    token = await _cdse_token(client)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    catalog_ok = False
    last_err = None
    for spec in attempts:
        bbox = scene_bbox(lat, lon, spec["nm"])
        body = {
            "collections": [STAC_COLLECTION],
            "bbox": bbox,
            "datetime": f"{spec['start']}/{now}",
            "limit": max(MAX_SCENES, 5),
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }
        if spec["cloud"] is not None:
            body["query"] = {"eo:cloud_cover": {"lt": spec["cloud"]}}
        try:
            r = await client.post(STAC_SEARCH, json=body, headers=headers, timeout=12.0)
            if r.status_code >= 400:
                if bag.get("http_status") is None:
                    bag["http_status"] = r.status_code
                last_err = f"HTTP {r.status_code}"
                continue
            bag["http_status"] = r.status_code
            catalog_ok = True
            payload = r.json() if r.content else {}
        except httpx.HTTPStatusError as exc:
            bag["http_status"] = exc.response.status_code if exc.response is not None else None
            last_err = f"HTTP {bag['http_status']}"
            continue
        except Exception as exc:
            last_err = layer_code("", type(exc).__name__)
            continue
        features = payload.get("features") if isinstance(payload, dict) else []
        scenes = []
        for feat in features or []:
            item = slim_stac_scene(feat, lat, lon)
            if item:
                scenes.append(item)
        scenes.sort(key=lambda s: (
            999.0 if s.get("cloud_cover") is None else float(s["cloud_cover"]),
            s.get("datetime") or "",
        ))
        if scenes:
            bag["scene"] = scenes[0]
            bag["scenes"] = scenes[:MAX_SCENES]
            bag["source"] = "cdse-stac"
            bag["reason"] = None
            bag["link"] = scenes[0].get("link") or bag["link"]
            bag["bbox"] = scenes[0].get("bbox") or bbox
            return bag
    bag["source"] = "cdse-stac"
    if catalog_ok:
        bag["reason"] = "no_scene_in_bbox"
    elif bag.get("http_status"):
        bag["reason"] = f"cdse_stac_unavailable:{bag['http_status']}"
    else:
        bag["reason"] = layer_code("cdse_stac_unavailable", last_err or "error")
    return bag


def attach_derived_from_science(satellites: dict, science_items: list | None) -> dict:
    out = dict(satellites or empty_satellites())
    derived = {k: dict(v) for k, v in (out.get("derived") or DERIVED_NULL).items()}
    for item in science_items or []:
        if (item.get("source") or "") != "sentinel-pilot":
            continue
        kind = str(item.get("kind") or "")
        payload = {
            "value": {
                "name": item.get("name"),
                "kind": kind or "dataset",
                "url": item.get("url"),
                "doi": item.get("doi"),
                "nm": item.get("nm"),
                "method": item.get("method"),
                "error_m": item.get("error_m"),
            },
            "source": "sentinel-pilot",
            "reason": None,
        }
        if kind == "coastline" or "coast" in str(item.get("name") or "").lower():
            derived["coastline"] = payload
        elif kind in ("depth_area", "sdb", "depth") or item.get("error_m") is not None:
            derived["sdb"] = payload
        elif kind == "intertidal":
            derived["intertidal"] = payload
    out["derived"] = derived
    return out


def hycom_lon(lon: float) -> float:
    """Wrap geographic longitude into the RTOFS/HYCOM 74–434 range."""
    return wrap_lon_into(lon, RTOFS_HYCOM_WEST)


def geo_from_hycom(h_lon: float) -> float:
    return wrap_lon(h_lon)


def rtofs_is_fill(value: Any) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return True
    return (not math.isfinite(v)) or abs(v) >= RTOFS_FILL


def rtofs_from_uv(u_ms: float, v_ms: float, issued: str | None = None) -> dict:
    speed_kn = math.hypot(float(u_ms), float(v_ms)) * RTOFS_MS_TO_KN
    dir_to = (math.degrees(math.atan2(float(u_ms), float(v_ms))) + 360.0) % 360.0
    return {
        "kind": "forecast",
        "source": "noaa-rtofs",
        "speedKnots": round(speed_kn, 2),
        "dirToDeg": round(dir_to, 1),
        "u_ms": round(float(u_ms), 4),
        "v_ms": round(float(v_ms), 4),
        "issued": issued,
    }


class _HttpRangeIO:
    """File-like HTTP Range reader so h5py can open a remote NetCDF4."""

    def __init__(self, url: str, size: int, headers: dict | None = None):
        self.name = url
        self.url = url
        self._size = int(size)
        self._headers = dict(headers or {})
        self._pos = 0
        self._chunk = 256 * 1024
        self._cache: dict[int, bytes] = {}
        self._cache_order: list[int] = []
        self._client = httpx.Client(
            timeout=30.0,
            headers=self._headers,
            follow_redirects=True,
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = int(offset)
        elif whence == 1:
            self._pos += int(offset)
        else:
            self._pos = self._size + int(offset)
        return self._pos

    def _chunk_bytes(self, idx: int) -> bytes:
        if idx in self._cache:
            return self._cache[idx]
        c0 = idx * self._chunk
        c1 = min(c0 + self._chunk, self._size) - 1
        r = self._client.get(
            self.url,
            headers={**self._headers, "Range": f"bytes={c0}-{c1}"},
        )
        if r.status_code not in (200, 206):
            r.raise_for_status()
        data = r.content
        self._cache[idx] = data
        self._cache_order.append(idx)
        while len(self._cache_order) > 80:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)
        return data

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self._size - self._pos
        if n <= 0 or self._pos >= self._size:
            return b""
        start = self._pos
        end = min(self._pos + int(n), self._size)
        out = bytearray()
        pos = start
        while pos < end:
            idx = pos // self._chunk
            chunk = self._chunk_bytes(idx)
            off = pos - idx * self._chunk
            take = min(len(chunk) - off, end - pos)
            if take <= 0:
                break
            out.extend(chunk[off:off + take])
            pos += take
        self._pos = end
        return bytes(out)


_rtofs_lock = threading.Lock()
_rtofs_h5: dict[str, Any] = {
    "url": None,
    "io": None,
    "file": None,
    "lat_col": None,
    "nj": None,
    "ni": None,
}


def reset_rtofs_cache() -> None:
    with _rtofs_lock:
        _close_rtofs_unlocked()


atexit.register(reset_rtofs_cache)


def _close_rtofs_unlocked() -> None:
    fh = _rtofs_h5.get("file")
    io = _rtofs_h5.get("io")
    try:
        if fh is not None:
            fh.close()
    except Exception:
        pass
    try:
        if io is not None:
            io.close()
    except Exception:
        pass
    _rtofs_h5.update({
        "url": None,
        "io": None,
        "file": None,
        "lat_col": None,
        "nj": None,
        "ni": None,
    })


def _rtofs_file_size(url: str, headers: dict) -> int:
    with httpx.Client(timeout=20.0, headers=headers, follow_redirects=True) as client:
        try:
            r = client.head(url)
            if r.status_code < 400:
                size = int(r.headers.get("content-length") or 0)
                if size > 0:
                    return size
        except Exception:
            pass
        r = client.get(url, headers={**headers, "Range": "bytes=0-0"})
        if r.status_code not in (200, 206):
            r.raise_for_status()
        cr = r.headers.get("content-range") or ""
        m = re.search(r"/(\d+)\s*$", cr)
        if m:
            return int(m.group(1))
        size = int(r.headers.get("content-length") or 0)
        if size > 1:
            return size
    raise RuntimeError("rtofs_size_unknown")


def _open_rtofs_unlocked(url: str):
    if _rtofs_h5.get("url") == url and _rtofs_h5.get("file") is not None:
        return _rtofs_h5["file"]
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError("h5py_missing") from exc
    _close_rtofs_unlocked()
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    size = _rtofs_file_size(url, headers)
    io = _HttpRangeIO(url, size, headers)
    fh = h5py.File(io, "r")
    lat = fh["Latitude"]
    nj, ni = int(lat.shape[0]), int(lat.shape[1])
    mid = ni // 2
    lat_col = lat[:, mid][()]
    _rtofs_h5.update({
        "url": url,
        "io": io,
        "file": fh,
        "lat_col": lat_col,
        "nj": nj,
        "ni": ni,
    })
    return fh


def _nearest_index(axis, value: float) -> int:
    import numpy as np
    arr = np.asarray(axis)
    if arr.size == 0:
        return 0
    if arr[0] > arr[-1]:
        idx = int(arr.size - 1 - np.searchsorted(arr[::-1], value))
    else:
        idx = int(np.searchsorted(arr, value))
    return max(0, min(int(arr.size) - 1, idx))


def _rtofs_lookup_sync(url: str, lat: float, lon: float) -> tuple[float, float] | None:
    with _rtofs_lock:
        fh = _open_rtofs_unlocked(url)
        lat_col = _rtofs_h5["lat_col"]
        nj = _rtofs_h5["nj"]
        ni = _rtofs_h5["ni"]
        j0 = _nearest_index(lat_col, lat)
        lon_row = fh["Longitude"][j0, :][()]
        target = hycom_lon(lon)
        i0 = _nearest_index(lon_row, target)
        j1 = max(0, j0 - 3)
        j2 = min(nj, j0 + 4)
        i1 = max(0, i0 - 3)
        i2 = min(ni, i0 + 4)
        lat_w = fh["Latitude"][j1:j2, i1:i2][()]
        lon_w = fh["Longitude"][j1:j2, i1:i2][()]
        u_w = fh["u_velocity"][0, 0, j1:j2, i1:i2][()]
        v_w = fh["v_velocity"][0, 0, j1:j2, i1:i2][()]
    best = None
    best_d = None
    best_uv = None
    for jj in range(lat_w.shape[0]):
        for ii in range(lat_w.shape[1]):
            u = float(u_w[jj, ii])
            v = float(v_w[jj, ii])
            if rtofs_is_fill(u) or rtofs_is_fill(v):
                continue
            dlat = float(lat_w[jj, ii]) - lat
            dlon = delta_lon(lon, geo_from_hycom(float(lon_w[jj, ii])))
            dist = dlat * dlat + dlon * dlon
            if best_d is None or dist < best_d:
                best_d = dist
                best = (j1 + jj, i1 + ii)
                best_uv = (u, v)
    if best_uv is None:
        return None
    return best_uv


async def _rtofs_latest_url(client: httpx.AsyncClient) -> tuple[str, str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html, */*"}
    r = await client.get(RTOFS_PROD, headers=headers, timeout=10.0)
    r.raise_for_status()
    dates = sorted(set(re.findall(r"rtofs\.(\d{8})", r.text)))
    if not dates:
        raise RuntimeError("rtofs_no_cycle")
    for day in reversed(dates[-3:]):
        listing = f"{RTOFS_PROD}rtofs.{day}/"
        try:
            lr = await client.get(listing, headers=headers, timeout=10.0)
            if lr.status_code >= 400:
                continue
            text = lr.text
        except Exception:
            continue
        for name in RTOFS_PROG_NAMES:
            if name in text:
                issued = f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00Z"
                return f"{listing}{name}", issued, name
    raise RuntimeError("rtofs_no_prog")


async def fetch_rtofs_current(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
) -> tuple[dict | None, str | None]:
    try:
        url, issued, name = await _rtofs_latest_url(client)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
        return None, layer_code("rtofs_unavailable", status if status else type(exc).__name__)
    except Exception as exc:
        detail = str(exc) if str(exc) in {"rtofs_no_cycle", "rtofs_no_prog", "h5py_missing"} else type(exc).__name__
        return None, layer_code("rtofs_unavailable", detail)
    try:
        uv = await asyncio.to_thread(_rtofs_lookup_sync, url, lat, lon)
    except RuntimeError as exc:
        return None, layer_code("rtofs_unavailable", str(exc))
    except Exception as exc:
        return None, layer_code("rtofs_unavailable", type(exc).__name__)
    if uv is None:
        return None, "off_grid"
    bag = rtofs_from_uv(uv[0], uv[1], issued=issued)
    bag["product"] = name
    bag["url"] = url
    return bag, None


class WeatherFetchError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _sync_weather_client(timeout: float = 8.0) -> httpx.Client:
    from weather_pipeline import weather_http_transport
    kwargs: dict[str, Any] = {"timeout": timeout}
    transport = weather_http_transport()
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


def load_openmeteo_gfs(lat: float, lon: float) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with _sync_weather_client() as client:
        try:
            r = client.get(
                OPEN_METEO_FORECAST,
                params={
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                    "current": "wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "kn",
                    "models": "gfs_global",
                    "timezone": "UTC",
                },
                headers=headers,
            )
            r.raise_for_status()
            cur = (r.json() or {}).get("current") or {}
        except httpx.HTTPStatusError:
            raise WeatherFetchError(layer_code("openmeteo_unavailable", "HTTPStatusError")) from None
        except WeatherFetchError:
            raise
        except Exception as exc:
            raise WeatherFetchError(layer_code("openmeteo_unavailable", type(exc).__name__)) from exc
    if cur.get("wind_speed_10m") is None:
        raise WeatherFetchError("openmeteo_empty")
    return {
        "kind": "forecast",
        "source": "openmeteo-gfs",
        "speedKnots": float(cur["wind_speed_10m"]),
        "dirFromDeg": float(cur.get("wind_direction_10m") or 0),
        "time": cur.get("time"),
    }


def load_openmeteo_gfs_wave(lat: float, lon: float) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with _sync_weather_client() as client:
        try:
            r = client.get(
                OPEN_METEO_MARINE,
                params={
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                    "current": "wave_height,wave_direction,wave_period",
                    "models": "ncep_gfswave025",
                    "timezone": "UTC",
                },
                headers=headers,
            )
            r.raise_for_status()
            cur = (r.json() or {}).get("current") or {}
        except Exception:
            return {}
    if cur.get("wave_height") is None:
        return {}
    return {
        "kind": "forecast",
        "source": "openmeteo-gfs-wave",
        "hs": float(cur["wave_height"]),
        "dirDeg": cur.get("wave_direction"),
        "periodS": cur.get("wave_period"),
        "time": cur.get("time"),
    }


def load_rtofs_current(lat: float, lon: float) -> dict:
    async def _run():
        from weather_pipeline import weather_http_transport
        kwargs: dict[str, Any] = {"timeout": 10.0}
        transport = weather_http_transport()
        if transport is not None:
            kwargs["transport"] = transport
        async with httpx.AsyncClient(**kwargs) as client:
            current, reason = await fetch_rtofs_current(client, lat, lon)
            return {"current": current, "current_reason": reason}

    return asyncio.run(_run())


def _product_from_snapshot(part: dict, keys: tuple[str, ...]) -> dict | None:
    if part.get("status") != "ready":
        return None
    if not any(part.get(key) is not None for key in keys):
        return None
    out = {}
    for key in ("kind", "source", *keys, "time"):
        if key in part:
            out[key] = part[key]
    return out or None


def compose_ici_weather(group: dict) -> dict:
    bag = empty_weather()
    bag["status"] = group.get("status") or "pending"
    bag["refreshing"] = bool(group.get("refreshing"))
    bag["cycle"] = group.get("cycle")
    bag["cell"] = group.get("cell")
    bag["issued"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wind_p = group.get("wind") or {}
    wave_p = group.get("wave") or {}
    curr_p = group.get("current") or {}
    wind = _product_from_snapshot(wind_p, ("speedKnots", "dirFromDeg"))
    wave = _product_from_snapshot(wave_p, ("hs", "dirDeg", "periodS"))
    current = curr_p.get("current") if curr_p.get("status") == "ready" else None
    current_reason = curr_p.get("current_reason") if curr_p.get("status") == "ready" else None
    if curr_p.get("status") == "error" and not current_reason:
        current_reason = f"rtofs_unavailable:{curr_p.get('reason') or 'Error'}"
    bag["wind"] = wind
    bag["wave"] = wave
    bag["current"] = current
    bag["current_reason"] = current_reason
    if bag["status"] == "pending":
        bag["reason"] = None
        bag["source"] = None
        return bag
    if not wind and not wave and current is None:
        reason = None
        if wind_p.get("status") == "error":
            reason = wind_p.get("reason") or "openmeteo_unavailable:Error"
        elif wind_p.get("reason"):
            reason = wind_p["reason"]
        bag["reason"] = reason or "openmeteo_empty"
        bag["source"] = "openmeteo" if reason else "noaa-rtofs"
        return bag
    models = []
    if wind or wave:
        models.append("GFS 0.25° / GFS-Wave 0.25° (Open-Meteo)")
    if current:
        models.append("RTOFS Global 1/12°")
    bag["reason"] = None
    bag["source"] = "openmeteo-gfs+noaa-rtofs" if (wind or wave) and current else (
        "noaa-rtofs" if current else "openmeteo-gfs"
    )
    bag["model"] = " + ".join(models) if models else "Open-Meteo"
    return bag


def snapshot_ici_weather(lat: float, lon: float, *, when=None) -> dict:
    from weather_pipeline import route_snapshot_group
    group = route_snapshot_group(
        (
            ("wind", "openmeteo-gfs", lambda: load_openmeteo_gfs(lat, lon)),
            ("wave", "openmeteo-gfs-wave", lambda: load_openmeteo_gfs_wave(lat, lon)),
            ("current", "noaa-rtofs", lambda: load_rtofs_current(lat, lon)),
        ),
        lat,
        lon,
        when=when,
    )
    return compose_ici_weather(group)


async def fetch_weather_forecast(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
) -> dict:
    from weather_pipeline import bind_weather_transport
    if client is not None:
        bind_weather_transport(getattr(client, "_transport", None))
    return snapshot_ici_weather(lat, lon)


def _depth_from_emodnet_payload(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict) or payload.get("avg") is None:
        if isinstance(payload, dict) and payload.get("depth_m") is not None:
            return {
                "kind": "observation",
                "source": payload.get("source") or "emodnet-bathymetry",
                "depth_m": payload.get("depth_m"),
                "on_land": payload.get("on_land"),
            }
        return None
    try:
        raw = float(payload["avg"])
    except (TypeError, ValueError):
        return None
    depth_m = raw if raw >= 0 else -raw
    on_land = raw >= 0 and raw < 0.3
    return {
        "kind": "observation",
        "source": "emodnet-bathymetry",
        "depth_m": round(depth_m, 1),
        "on_land": on_land,
        "raw": raw,
    }


SEABED_LABEL_KEYS = (
    "substrate", "SUBSTRATE", "folk_5", "FOLK_5", "folk_7", "FOLK_7",
    "gray_cin", "GRAY_CIN", "folk5", "class", "CLASS", "sediment",
    "SEDIMENT", "substrate_class",
)


def _seabed_label(props: dict) -> str | None:
    for key in SEABED_LABEL_KEYS:
        val = props.get(key)
        if val not in (None, ""):
            return str(val)
    return None


def _gfi_properties(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    feats = payload.get("features")
    if isinstance(feats, list) and feats:
        props = feats[0].get("properties") or {}
        return props if isinstance(props, dict) else None
    if payload.get("type") == "Feature":
        props = payload.get("properties") or {}
        return props if isinstance(props, dict) else None
    return None


async def _wms_feature_info(
    client: httpx.AsyncClient,
    url: str,
    layers: str,
    lat: float,
    lon: float,
) -> dict | None:
    delta = 0.02
    # WMS 1.3.0 + EPSG:4326 = lat,lon order.
    bbox = f"{lat - delta},{lon - delta},{lat + delta},{lon + delta}"
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": layers,
        "QUERY_LAYERS": layers,
        "INFO_FORMAT": "application/json",
        "CRS": "EPSG:4326",
        "BBOX": bbox,
        "WIDTH": "101",
        "HEIGHT": "101",
        "I": "50",
        "J": "50",
        "FEATURE_COUNT": "3",
    }
    r = await client.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=8.0,
    )
    r.raise_for_status()
    ctype = (r.headers.get("content-type") or "").lower()
    if "json" not in ctype:
        return None
    return r.json() if r.content else None


async def fetch_emodnet_point(
    client: httpx.AsyncClient,
    bi: str,
    lat: float,
    lon: float,
) -> dict:
    bag = empty_emodnet()
    bathy = None
    try:
        r = await client.get(
            f"{bi}/depth",
            params={"lat": lat, "lon": lon},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=8.0,
        )
        r.raise_for_status()
        bathy = _depth_from_emodnet_payload(r.json() if r.content else None)
    except Exception:
        bathy = None
    if bathy is None:
        try:
            r = await client.get(
                EMODNET_DEPTH,
                params={"geom": f"POINT({lon} {lat})"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=10.0,
            )
            r.raise_for_status()
            bathy = _depth_from_emodnet_payload(r.json() if r.content else None)
        except Exception as exc:
            bathy = {
                "value": None,
                "source": "emodnet-bathymetry",
                "reason": layer_code("depth_sample_unavailable", type(exc).__name__),
            }
    if bathy is None:
        bathy = {
            "value": None,
            "source": "emodnet-bathymetry",
            "reason": "no_sample_at_point",
        }
    seabed = None
    try:
        raw = await _wms_feature_info(
            client, EMODNET_SEABED_WMS, "seabed_substrate_1m", lat, lon,
        )
        props = _gfi_properties(raw)
        if props:
            label = _seabed_label(props)
            seabed = {
                "kind": "observation",
                "source": "emodnet-geology",
                "label": label,
                "reason": None if label else "no_substrate_class",
                "properties": {k: props[k] for k in list(props)[:8]},
            }
        else:
            seabed = {
                "value": None,
                "source": "emodnet-geology",
                "reason": "no_feature_at_point",
            }
    except Exception as exc:
        seabed = {
            "value": None,
            "source": "emodnet-geology",
                "reason": layer_code("wms_unavailable", type(exc).__name__),
        }
    cables = None
    try:
        raw = await _wms_feature_info(
            client, EMODNET_CABLES_WMS, "telecablesactual,powercables", lat, lon,
        )
        props = _gfi_properties(raw)
        if props:
            cables = {
                "kind": "observation",
                "source": "emodnet-human-activities",
                "nearby": True,
                "name": props.get("name") or props.get("NAME") or props.get("status"),
                "properties": {k: props[k] for k in list(props)[:8]},
            }
        else:
            cables = {
                "kind": "observation",
                "source": "emodnet-human-activities",
                "nearby": False,
                "reason": "no_feature_at_point",
            }
    except Exception as exc:
        cables = {
            "value": None,
            "source": "emodnet-human-activities",
                "reason": layer_code("wms_unavailable", type(exc).__name__),
        }
    bag.update({
        "bathy": bathy,
        "seabed": seabed,
        "cables": cables,
        "reason": None,
    })
    return bag


def slim_aton_feature(feat: dict, lat0: float, lon0: float, haversine_nm) -> dict | None:
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    lat = props.get("lat")
    lon = props.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        if geom.get("type") == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
        else:
            return None
    name = (
        props.get("name")
        or props.get("OBJNAM")
        or props.get("seamark:name")
        or props.get("kind")
        or ""
    )
    if not str(name).strip():
        return None
    return {
        "name": str(name).strip()[:120],
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "nm": round(haversine_nm(lat0, lon0, float(lat), float(lon)), 1),
        "kind": props.get("kind") or props.get("seamark:type"),
        "source": props.get("source") or "noaa",
    }


def aton_from_overpass(elements: list, lat0: float, lon0: float, haversine_nm) -> list[dict]:
    found = []
    for el in elements or []:
        tags = el.get("tags") or {}
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        name = tags.get("seamark:name") or tags.get("name") or tags.get("seamark:type")
        if not name:
            continue
        found.append({
            "name": str(name)[:120],
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "nm": round(haversine_nm(lat0, lon0, float(lat), float(lon)), 1),
            "kind": tags.get("seamark:type"),
            "source": "osm-overpass",
        })
    found.sort(key=lambda x: x["nm"])
    return found[:MAX_ATON]


async def fetch_noaa_aids(
    client: httpx.AsyncClient,
    bi: str,
    bbox: tuple[float, float, float, float],
    lat: float,
    lon: float,
    haversine_nm,
    radius_nm: float,
) -> list[dict]:
    if not bbox_intersects_us(bbox):
        return []
    west, south, east, north = bbox
    try:
        r = await client.get(
            f"{bi}/noaa/aids",
            params={"bbox": f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=12.0,
        )
        r.raise_for_status()
        data = r.json() if r.content else {}
    except Exception:
        return []
    found = []
    for feat in (data.get("features") if isinstance(data, dict) else []) or []:
        item = slim_aton_feature(feat, lat, lon, haversine_nm)
        if item and item["nm"] <= radius_nm + 0.05:
            found.append(item)
    found.sort(key=lambda x: x["nm"])
    return found[:MAX_ATON]


def _overpass_latlon(el: dict) -> tuple[float, float] | None:
    lat = el.get("lat")
    lon = el.get("lon")
    if lat is None or lon is None:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


async def _overpass_elements(
    client: httpx.AsyncClient,
    query: str,
) -> tuple[list, str | None]:
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            r = await client.post(
                url,
                content=query.encode("utf-8"),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "text/plain",
                },
                timeout=14.0,
            )
            r.raise_for_status()
            data = r.json() if r.content else {}
            elements = data.get("elements") if isinstance(data, dict) else []
            return list(elements or []), None
        except Exception as exc:
            last_err = layer_code("", type(exc).__name__)
            continue
    return [], layer_code("overpass_unavailable", last_err or "error")


def is_harbour_master(tags: dict | None) -> bool:
    tags = tags or {}
    return (
        tags.get("office") == "harbour_master"
        or tags.get("seamark:building:function") == "harbour_master"
        or tags.get("harbour") == "harbour_master"
    )


def harbour_masters_from_overpass(
    elements: list,
    lat0: float,
    lon0: float,
    haversine_nm,
    limit: int = 3,
) -> list[dict]:
    found = []
    for el in elements or []:
        tags = el.get("tags") or {}
        if not is_harbour_master(tags):
            continue
        pos = _overpass_latlon(el)
        if pos is None:
            continue
        lat, lon = pos
        name = tags.get("name") or tags.get("seamark:name") or tags.get("official_name")
        if not name:
            continue
        found.append({
            "name": str(name)[:120],
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "nm": round(haversine_nm(lat0, lon0, lat, lon), 1),
            "source": "osm-overpass",
        })
    found.sort(key=lambda x: x["nm"])
    return found[:limit]


GENERIC_ANCHORAGE_NAMES = {"anchorage", "anchor_berth", "mooring"}


def _anchorage_type(tags: dict) -> str | None:
    seamark = str(tags.get("seamark:type") or "")
    if seamark in ("anchorage", "anchor_berth", "mooring"):
        return seamark
    if tags.get("leisure") == "anchorage":
        return "anchorage"
    return None


def anchorages_from_overpass(
    elements: list,
    lat0: float,
    lon0: float,
    haversine_nm,
    limit: int = 5,
) -> list[dict]:
    found = []
    for el in elements or []:
        tags = el.get("tags") or {}
        kind = _anchorage_type(tags)
        if not kind:
            continue
        pos = _overpass_latlon(el)
        if pos is None:
            continue
        lat, lon = pos
        named = tags.get("name") or tags.get("seamark:name")
        name = named or tags.get("seamark:anchorage:category") or kind
        found.append({
            "name": str(name)[:120],
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "nm": round(haversine_nm(lat0, lon0, lat, lon), 1),
            "anchorage_type": kind,
            "source": "osm-overpass",
            "_named": bool(named),
        })
    found.sort(key=lambda x: (0 if x["_named"] else 1, x["nm"]))
    out = found[:limit]
    for item in out:
        item.pop("_named", None)
    return out


async def fetch_overpass_harbours(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    radius_nm: float,
    haversine_nm,
    max_capitaineries: int = 3,
    max_anchorages: int = 5,
) -> tuple[list[dict], list[dict]]:
    """One Overpass call: harbour_master + named OSM anchorages around the boat."""
    radius_nm = min(float(radius_nm or 15.0), 15.0)
    around = f"(around:{int(radius_nm * 1852)},{lat:.5f},{lon:.5f})"
    parts = []
    if max_capitaineries:
        parts.extend((
            f'nwr["office"="harbour_master"]{around};',
            f'nwr["seamark:building:function"="harbour_master"]{around};',
            f'nwr["harbour"="harbour_master"]{around};',
        ))
    if max_anchorages:
        parts.extend((
            f'nwr["seamark:type"="anchorage"]{around};',
            f'nwr["seamark:type"="anchor_berth"]{around};',
            f'nwr["leisure"="anchorage"]{around};',
        ))
    if not parts:
        return [], []
    query = f"[out:json][timeout:20];({''.join(parts)});out center tags;"
    elements, _err = await _overpass_elements(client, query)
    return (
        harbour_masters_from_overpass(
            elements, lat, lon, haversine_nm, max_capitaineries,
        ),
        anchorages_from_overpass(
            elements, lat, lon, haversine_nm, max_anchorages,
        ),
    )


async def fetch_overpass_aton(
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float],
    lat: float,
    lon: float,
    haversine_nm,
) -> tuple[list[dict], str | None]:
    west, south, east, north = bbox
    query = (
        f"[out:json][timeout:12];"
        f'(node["seamark:type"~"^(light|light_major|light_minor|buoy|buoy_lateral|'
        f'buoy_cardinal|buoy_special_purpose|beacon|beacon_lateral|beacon_cardinal)$"]'
        f"({south:.5f},{west:.5f},{north:.5f},{east:.5f}););"
        f"out body 20;"
    )
    elements, err = await _overpass_elements(client, query)
    if err:
        return [], err
    return aton_from_overpass(elements, lat, lon, haversine_nm), None


async def fetch_aton(
    client: httpx.AsyncClient,
    bi: str,
    lat: float,
    lon: float,
    radius_nm: float,
    haversine_nm,
    radius_bbox,
) -> dict:
    bag = empty_aton()
    bbox = radius_bbox(lat, lon, radius_nm)
    noaa = await fetch_noaa_aids(client, bi, bbox, lat, lon, haversine_nm, radius_nm)
    osm, osm_err = await fetch_overpass_aton(client, bbox, lat, lon, haversine_nm)
    merged: dict[tuple, dict] = {}
    for item in noaa + osm:
        key = (round(item["lat"], 4), round(item["lon"], 4), item["name"])
        if key not in merged or item["nm"] < merged[key]["nm"]:
            merged[key] = item
    nearby = sorted(merged.values(), key=lambda x: x["nm"])[:MAX_ATON]
    sources = []
    if noaa:
        sources.append("noaa-enc")
    if osm:
        sources.append("osm-overpass")
    bag["nearby"] = nearby
    if sources:
        bag["source"] = "+".join(sources)
        bag["reason"] = None
    elif osm_err and not bbox_intersects_us(bbox):
        bag["source"] = None
        bag["reason"] = f"outside_us_enc;{osm_err}"
    elif osm_err:
        bag["source"] = "noaa-enc"
        bag["reason"] = osm_err
    elif not bbox_intersects_us(bbox):
        bag["source"] = None
        bag["reason"] = "outside_us_enc;no_osm_seamark"
    else:
        bag["source"] = "noaa-enc"
        bag["reason"] = "no_aid_in_bbox"
    return bag


def bi_review_headers() -> dict:
    """En-têtes vers l'API Blue Intelligence pour les fiches de vérification.

    En production BI protège `/review/fiche` (ADMIN_KEY → en-tête X-Admin-Key).
    Le simulateur envoie la clé s'il en a une (`BI_ADMIN_KEY` dans
    simulator.env) ; sinon la fiche revient 401 → `review_requires_admin`,
    que le briefing ne raconte plus au visiteur.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    key = (os.getenv("BI_ADMIN_KEY") or "").strip()
    if key:
        headers["X-Admin-Key"] = key
    return headers


async def fetch_review(
    client: httpx.AsyncClient,
    bi: str,
    zee: dict | None,
    nearest_amp: dict | None,
) -> dict:
    bag = empty_review()
    headers = bi_review_headers()
    mrgid = zee.get("mrgid") if zee else None
    got = False
    if mrgid:
        try:
            r = await client.get(
                f"{bi}/review/fiche",
                params={"kind": "eez", "id": str(mrgid)},
                headers=headers,
                timeout=5.0,
            )
            if r.status_code == 401:
                bag["reason"] = "review_requires_admin"
                bag["http_status"] = 401
                bag["url"] = str(r.url)
                bag["source"] = "review_fiche"
                return bag
            bag["http_status"] = r.status_code
            bag["url"] = str(r.url)
            if r.status_code == 404:
                bag["zee"] = {
                    "gold_on": None,
                    "source": "review_fiche",
                    "reason": "fiche_not_found",
                    "id": mrgid,
                }
            else:
                r.raise_for_status()
                data = r.json() if r.content else {}
                bag["zee"] = {
                    "gold_on": data.get("gold_on"),
                    "gold_ready": data.get("gold_ready"),
                    "pre_gold": data.get("pre_gold"),
                    "source": "review_fiche",
                    "id": mrgid,
                }
                got = True
        except Exception as exc:
            bag["reason"] = layer_code("review_unavailable", type(exc).__name__)
            return bag
    site_id = (nearest_amp or {}).get("site_id") or (nearest_amp or {}).get("id")
    if site_id:
        try:
            r = await client.get(
                f"{bi}/review/fiche",
                params={"kind": "amp", "id": str(site_id)},
                headers=headers,
                timeout=5.0,
            )
            if r.status_code == 200:
                data = r.json() if r.content else {}
                bag["amp"] = {
                    "gold_on": data.get("gold_on"),
                    "gold_ready": data.get("gold_ready"),
                    "pre_gold": data.get("pre_gold"),
                    "source": "review_fiche",
                    "id": site_id,
                    "name": nearest_amp.get("name") if nearest_amp else None,
                }
                got = True
            elif r.status_code == 401 and not bag.get("reason"):
                bag["reason"] = "review_requires_admin"
            elif r.status_code == 404:
                bag["amp"] = {
                    "gold_on": None,
                    "source": "review_fiche",
                    "reason": "fiche_not_found",
                    "id": site_id,
                }
        except Exception:
            if not bag.get("amp"):
                bag["amp"] = {
                    "gold_on": None,
                    "source": "review_fiche",
                    "reason": "review_unavailable",
                    "id": site_id,
                }
    if got:
        bag["source"] = "review_fiche"
        if bag.get("reason") == "review_requires_admin":
            bag["reason"] = None
    elif not bag.get("reason") and not mrgid and not site_id:
        bag["reason"] = "no_entity"
    return bag


def climatology_rose(point: dict | None) -> dict | None:
    if not isinstance(point, dict):
        return None
    atlas = point.get("wind_atlas") or {}
    if not isinstance(atlas, dict):
        return None
    dirs = atlas.get("directions_from")
    if atlas.get("stat") not in ("rose", "average") and not dirs and atlas.get("calm_pct") is None:
        return None
    return {
        "stat": atlas.get("stat"),
        "sectors_deg": atlas.get("sectors_deg") or 45,
        "directions_from": dirs or [],
        "calm_pct": atlas.get("calm_pct"),
        "gale_pct": atlas.get("gale_pct"),
        "most_likely": atlas.get("most_likely"),
        "vector_mean": atlas.get("vector_mean"),
    }
