import { climoPointLngs } from "./climatologyWorld.js";

/** Maille RD8 : z ≤ 2 → 4°, z = 3 → 2°, z ≥ 4 → 1°. */
export const CLIMO_MESH_MAX_Z = 4;
export const CLIMO_WORLD_MAX_FEATURES = 90 * 45;
export const VIEW_DEBOUNCE_MS = 200;

export const climoRoseStats = {
  created: 0,
  reused: 0,
  removed: 0,
  shown: 0,
  markers: 0,
  syncs: 0,
};

export function resetClimoRoseStats() {
  climoRoseStats.created = 0;
  climoRoseStats.reused = 0;
  climoRoseStats.removed = 0;
  climoRoseStats.shown = 0;
  climoRoseStats.markers = 0;
  climoRoseStats.syncs = 0;
  publishClimoRoseStats();
}

export function publishClimoRoseStats(partial) {
  if (partial) Object.assign(climoRoseStats, partial);
  if (typeof window !== "undefined") {
    window.__climoRoseStats = { ...climoRoseStats };
  }
  return climoRoseStats;
}

export function emptyClimoPools() {
  return {
    wind: new Map(),
    waveP50: new Map(),
    waveP90: new Map(),
    waveMean: new Map(),
    current: new Map(),
  };
}

export function drainClimoPools(pools) {
  if (!pools) return;
  for (const pool of Object.values(pools)) pool?.clear?.();
}

/** Empreinte vue (zoom + cadre) : un moveend sans déplacement garde la même clé. */
export function climoViewKey(map, { digits = 3 } = {}) {
  if (!map || typeof map.getZoom !== "function") return "";
  const z = Math.round(Number(map.getZoom()) || 0);
  const b = typeof map.getBounds === "function" ? map.getBounds() : null;
  if (!b || typeof b.getWest !== "function") return `z${z}`;
  return [
    z,
    b.getWest().toFixed(digits),
    b.getSouth().toFixed(digits),
    b.getEast().toFixed(digits),
    b.getNorth().toFixed(digits),
  ].join(":");
}

/** Remet les marqueurs du pool sur un groupe neuf (remontage d'effet). */
export function reattachClimoPool(group, pool) {
  if (!group || !pool) return 0;
  let n = 0;
  for (const lyr of pool.values()) {
    if (!lyr) continue;
    if (typeof group.hasLayer === "function" && group.hasLayer(lyr)) continue;
    if (typeof group.addLayer !== "function") continue;
    group.addLayer(lyr);
    n += 1;
  }
  return n;
}

/** 2e passe même vue : incrémente syncs sans recréer. */
export function publishSameViewWindSync(pool, syncs) {
  const n = pool?.size || 0;
  return publishClimoRoseStats({
    created: 0,
    reused: n,
    removed: 0,
    shown: n,
    markers: n,
    syncs,
  });
}

export function climoMeshDeg(zoom) {
  const z = Math.max(0, Math.min(6, Math.round(Number(zoom) || 0)));
  return Math.max(1, 16 / 2 ** Math.min(z, CLIMO_MESH_MAX_Z));
}

export function climoMarkerKey(lat, lng) {
  return `${Number(lat)}:${Number(lng)}`;
}

function viewWestEast(bounds) {
  if (!bounds) return { west: NaN, east: NaN };
  if (typeof bounds.getWest === "function") {
    return { west: Number(bounds.getWest()), east: Number(bounds.getEast()) };
  }
  return { west: Number(bounds.west), east: Number(bounds.east) };
}

/**
 * Copies monde dont la longitude tombe dans la vue (plus une marge).
 * Vue monde (span ≥ 360°) : une seule copie, la plus proche du centre.
 * `lonOrCopies` accepte une longitude ou le tableau déjà produit par climoPointLngs.
 */
export function visibleClimoLngs(lonOrCopies, bounds, { padDeg = 40 } = {}) {
  const copies = Array.isArray(lonOrCopies) ? lonOrCopies : climoPointLngs(lonOrCopies);
  const { west, east } = viewWestEast(bounds);
  if (!copies.length) return [];
  if (!Number.isFinite(west) || !Number.isFinite(east)) return copies;

  const span = east - west;
  if (span >= 360 - 1e-6) {
    const mid = west + span / 2;
    let best = copies[0];
    let bestD = Infinity;
    for (const lng of copies) {
      const d = Math.abs(lng - mid);
      if (d < bestD) {
        bestD = d;
        best = lng;
      }
    }
    return [best];
  }

  const pad = Number(padDeg) || 0;
  if (west <= east) {
    const w = west - pad;
    const e = east + pad;
    return copies.filter((lng) => lng >= w && lng <= e);
  }
  const w = west - pad;
  const e = east + pad;
  return copies.filter((lng) => lng >= w || lng <= e);
}

export function decimateClimoFeatures(features, zoom, { maxCount = CLIMO_WORLD_MAX_FEATURES } = {}) {
  const step = climoMeshDeg(zoom);
  const seen = new Set();
  const out = [];
  for (const f of features || []) {
    const [lon, lat] = f.geometry?.coordinates || [];
    if (lat == null || lon == null) continue;
    const glat = Math.round(Number(lat) / step) * step;
    const glon = Math.round(Number(lon) / step) * step;
    const k = `${glat}:${glon}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(f);
  }
  if (out.length <= maxCount) return out;
  const stride = out.length / maxCount;
  const picked = [];
  const used = new Set();
  for (let i = 0; i < maxCount; i += 1) {
    const idx = Math.min(out.length - 1, Math.floor(i * stride));
    if (used.has(idx)) continue;
    used.add(idx);
    picked.push(out[idx]);
  }
  return picked;
}

/** Ancien coût : une clé par copie monde, toujours ×3. */
export function naiveRebuildKeys(features) {
  const keys = [];
  for (const f of features || []) {
    const [lon, lat] = f.geometry?.coordinates || [];
    if (lat == null || lon == null) continue;
    for (const lng of climoPointLngs(lon)) {
      keys.push(climoMarkerKey(lat, lng));
    }
  }
  return keys;
}

export function syncClimoPointMarkers({
  group,
  pool,
  features,
  zoom,
  bounds,
  makeLayer,
  copiesFor = (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
  maxCount = CLIMO_WORLD_MAX_FEATURES,
}) {
  const shown = decimateClimoFeatures(features, zoom, { maxCount });
  const nextKeys = new Set();
  let created = 0;
  let reused = 0;
  for (const f of shown) {
    const [lon, lat] = f.geometry?.coordinates || [];
    if (lat == null || lon == null) continue;
    const p = f.properties || {};
    for (const lng of copiesFor(lon)) {
      const key = climoMarkerKey(lat, lng);
      nextKeys.add(key);
      if (pool.has(key)) {
        reused += 1;
        const existing = pool.get(key);
        if (existing && group && typeof group.addLayer === "function") {
          if (typeof group.hasLayer !== "function" || !group.hasLayer(existing)) {
            group.addLayer(existing);
          }
        }
        continue;
      }
      const lyr = makeLayer([lat, lng], p);
      if (!lyr) continue;
      pool.set(key, lyr);
      group.addLayer(lyr);
      created += 1;
    }
  }
  if (nextKeys.size === 0 && pool.size > 0) {
    return {
      created: 0,
      reused: pool.size,
      removed: 0,
      shown: shown.length,
      markers: pool.size,
    };
  }
  let removed = 0;
  for (const [key, lyr] of [...pool.entries()]) {
    if (nextKeys.has(key)) continue;
    group.removeLayer(lyr);
    pool.delete(key);
    removed += 1;
  }
  return {
    created,
    reused,
    removed,
    shown: shown.length,
    markers: pool.size,
  };
}
