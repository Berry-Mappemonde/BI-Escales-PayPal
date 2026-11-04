/**
 * Atlas CMEMS / IBTrACS — GET /climatology/point.
 * kind: climatology. Never relabel as forecast / GRIB2.
 */

import { wrapLon } from "./geo.js";
import { zoneWindAt } from "./climatologyWind.js";

const viteEnv = (typeof import.meta !== "undefined" && import.meta.env) || {};
export const BI_BASE = viteEnv.VITE_BI_BASE ?? "/bi";

export function civilMonth(isoOrDate) {
  if (isoOrDate instanceof Date && !Number.isNaN(isoOrDate.getTime())) {
    return isoOrDate.getUTCMonth() + 1;
  }
  const raw = String(isoOrDate || "");
  const parsed = Date.parse(raw);
  if (Number.isFinite(parsed)) return new Date(parsed).getUTCMonth() + 1;
  return new Date().getUTCMonth() + 1;
}

export function clampMonth(month) {
  const n = Number(month);
  if (!Number.isFinite(n)) return 1;
  return Math.max(1, Math.min(12, Math.round(n)));
}

export function cellKey(lat, lon, month) {
  const la = Math.round(Number(lat) * 2) / 2;
  const lo = Math.round(Number(lon) * 2) / 2;
  return `${la}:${lo}:${clampMonth(month)}`;
}

export function atlasPointUrl({ lat, lon, month, destLat, destLon, day }) {
  const q = new URLSearchParams({
    lat: String(lat),
    lon: String(wrapLon(Number(lon))),
    month: String(clampMonth(month)),
  });
  if (Number.isFinite(Number(destLat)) && Number.isFinite(Number(destLon))) {
    q.set("dest_lat", String(destLat));
    q.set("dest_lon", String(wrapLon(Number(destLon))));
  }
  if (Number.isFinite(Number(day))) q.set("day", String(day));
  return `${BI_BASE}/climatology/point?${q.toString()}`;
}

export function atlasCrossingsUrl({ lat1, lon1, lat2, lon2, month, day }) {
  const q = new URLSearchParams({
    lat1: String(lat1),
    lon1: String(wrapLon(Number(lon1))),
    lat2: String(lat2),
    lon2: String(wrapLon(Number(lon2))),
    month: String(clampMonth(month)),
  });
  if (Number.isFinite(Number(day))) q.set("day", String(day));
  return `${BI_BASE}/climatology/crossings?${q.toString()}`;
}

export function atlasLayerUrl(kind, month, extra = {}) {
  const q = new URLSearchParams({ month: String(clampMonth(month)), ...extra });
  return `${BI_BASE}/climatology/${kind}.geojson?${q.toString()}`;
}

export function atlasTileUrl(kind, month, z, x, y, extra = {}) {
  const q = new URLSearchParams({ month: String(clampMonth(month)), ...extra });
  return `${BI_BASE}/climatology/${kind}/tiles/${z}/${x}/${y}.json?${q.toString()}`;
}

function boundNum(bounds, getter, key) {
  if (bounds && typeof bounds[getter] === "function") return Number(bounds[getter]());
  return Number(bounds?.[key]);
}

export function lonToTileX(lon, z) {
  const n = 2 ** z;
  return Math.floor(((Number(lon) + 180) / 360) * n);
}

export function latToTileY(lat, z) {
  const n = 2 ** z;
  const φ = (Math.max(-85, Math.min(85, Number(lat))) * Math.PI) / 180;
  return Math.floor((1 - Math.log(Math.tan(φ) + 1 / Math.cos(φ)) / Math.PI) / 2 * n);
}

/**
 * Visible XYZ tiles (Leaflet) plus an optional one-tile margin.
 * Antimeridian: west > east (e.g. 170 → −170) is split; x is taken modulo 2^z.
 */
export function visibleClimoTiles(bounds, zoom, { margin = 1, zMax = 6 } = {}) {
  const z = Math.max(0, Math.min(zMax, Math.round(Number(zoom) || 0)));
  const n = 2 ** z;
  const north = boundNum(bounds, "getNorth", "north");
  const south = boundNum(bounds, "getSouth", "south");
  const west = boundNum(bounds, "getWest", "west");
  const east = boundNum(bounds, "getEast", "east");
  const yA = latToTileY(north, z);
  const yB = latToTileY(south, z);
  const y0 = Math.max(0, Math.min(yA, yB) - margin);
  const y1 = Math.min(n - 1, Math.max(yA, yB) + margin);
  const tiles = [];
  const seen = new Set();

  const pushXRange = (x0, x1) => {
    for (let x = x0; x <= x1; x += 1) {
      const xx = ((x % n) + n) % n;
      for (let y = y0; y <= y1; y += 1) {
        const k = `${z}/${xx}/${y}`;
        if (seen.has(k)) continue;
        seen.add(k);
        tiles.push({ z, x: xx, y });
      }
    }
  };

  const span = east - west;
  if (!Number.isFinite(west) || !Number.isFinite(east) || span >= 360 - 1e-6) {
    pushXRange(0, n - 1);
  } else if (west <= east) {
    pushXRange(lonToTileX(west, z) - margin, lonToTileX(east, z) + margin);
  } else {
    pushXRange(lonToTileX(west, z) - margin, n - 1);
    pushXRange(0, lonToTileX(east, z) + margin);
  }
  return tiles;
}

/**
 * @returns {{
 *   speedKnots: number,
 *   dirFromDeg: number,
 *   source: "atlas",
 *   kind: "climatology",
 *   period: string | null,
 *   doi: object | null,
 *   periods: object | null,
 *   provenance: object | null,
 *   hsP50: number | null,
 *   hsP90: number | null,
 *   currentKn: number | null,
 *   currentToDeg: number | null,
 *   cycloneNearby: number | null,
 *   crossings: object | null,
 *   wave: object | null,
 *   current: object | null,
 *   cyclone: object | null,
 *   point: object,
 * } | null}
 */
export function windFromAtlasPoint(point) {
  if (!point || point.kind !== "climatology") return null;
  const rose = point.wind_atlas;
  const block = rose?.most_likely || rose?.vector_mean;
  if (!block || !Number.isFinite(Number(block.speed_knots))) return null;
  const wave = point.wave || null;
  const current = point.current || null;
  const cyclone = point.cyclone || null;
  return {
    speedKnots: Number(block.speed_knots),
    dirFromDeg: Number(block.dir_deg) || 0,
    source: "atlas",
    kind: "climatology",
    period: point.period || point.periods?.wind || null,
    doi: point.doi || null,
    periods: point.periods || null,
    provenance: point.provenance || null,
    hsP50: wave?.hs_p50_m ?? null,
    hsP90: wave?.hs_p90_m ?? null,
    currentKn: current?.speed_knots ?? null,
    currentToDeg: current?.direction_to_deg ?? null,
    cycloneNearby: cyclone?.nearby ?? null,
    crossings: cyclone?.crossings_if_leg || null,
    wave,
    current,
    cyclone,
    point,
  };
}

export function atlasOrZone(lat, lon, month, point) {
  const atlas = windFromAtlasPoint(point);
  if (atlas) return atlas;
  return {
    ...zoneWindAt(lat, lon, month),
    source: "zone_fallback",
    kind: "climatology",
    period: null,
    doi: null,
  };
}

export function compactAtlasFields(wind) {
  if (!wind) return {};
  return {
    source: wind.source || null,
    period: wind.period || null,
    doi: wind.doi || null,
    hsP50: wind.hsP50 ?? null,
    hsP90: wind.hsP90 ?? null,
    currentKn: wind.currentKn ?? null,
    currentToDeg: wind.currentToDeg ?? null,
    cycloneNearby: wind.cycloneNearby ?? null,
  };
}

export function hasAtlasBlocks(point) {
  if (!point || point.kind !== "climatology") return false;
  return Boolean(point.wind_atlas || point.wave || point.current || point.cyclone);
}
