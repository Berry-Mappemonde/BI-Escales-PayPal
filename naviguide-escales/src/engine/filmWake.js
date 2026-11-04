/**
 * Film wake: already-sailed track, cut at air hops
 * and at the antimeridian. Original NAVIGUIDE code — “trail”-style idea,
 * sans LeafletPlayback, TrackPlayBack ni deck.gl.
 */

import { lerpLon, splitAntimeridianCoords } from "../utils/geo.js";

/**
 * Last route point already reached at `sailNm`.
 * The previous cursor makes normal forward playback proportional only to
 * newly crossed vertices; seeks falling behind use a binary search.
 */
export function wakeCursorAt(flat, sailNm, previousIndex = -1) {
  const points = flat?.points || [];
  if (!points.length) return -1;
  const target = Math.max(0, Number(sailNm) || 0);
  const previousCum = points[previousIndex]?.cumNm ?? Infinity;
  if (previousIndex >= -1 && target >= previousCum - 1e-9) {
    let index = previousIndex;
    while (index + 1 < points.length && (points[index + 1].cumNm ?? 0) <= target + 1e-9) {
      index += 1;
    }
    return index;
  }

  let low = 0;
  let high = points.length - 1;
  let result = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if ((points[middle].cumNm ?? 0) <= target + 1e-9) {
      result = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return result;
}

/** Point interpolé le long du trait à `sailNm` (même formule que la queue du sillage). */
export function pointAtSailNm(flat, sailNm) {
  const pts = flat?.points || [];
  if (!pts.length) return null;
  const target = Math.max(0, Number(sailNm) || 0);
  const idx = wakeCursorAt(flat, target, -1);
  if (idx < 0) return { lat: pts[0].lat, lon: pts[0].lon, sailNm: 0 };
  const prev = pts[idx];
  const next = pts[idx + 1];
  if (!next || next.jump || prev.jump) {
    return { lat: prev.lat, lon: prev.lon, sailNm: prev.cumNm ?? target };
  }
  const span = ((next.cumNm ?? 0) - (prev.cumNm ?? 0)) || 1;
  const t = Math.max(0, Math.min(1, (target - (prev.cumNm ?? 0)) / span));
  const lon = lerpLon(prev.lon, next.lon, t);
  return {
    lat: prev.lat + t * (next.lat - prev.lat),
    lon,
    sailNm: target,
  };
}

/**
 * @returns {number[][][]} [lon, lat] parts up to sailNm
 */
export function wakeParts(flat, sailNm) {
  const pts = flat?.points || [];
  if (pts.length < 2) return [];
  const target = Math.max(0, Number(sailNm) || 0);
  const raw = [];
  let cur = [];

  const push = (lon, lat) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    cur.push([lon, lat]);
  };
  const flush = () => {
    if (cur.length >= 2) raw.push(cur);
    cur = [];
  };

  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    if ((p.cumNm ?? 0) > target + 1e-9) {
      const prev = i > 0 ? pts[i - 1] : null;
      if (prev && !p.jump && !prev.jump) {
        const span = ((p.cumNm ?? 0) - (prev.cumNm ?? 0)) || 1;
        const t = Math.max(0, Math.min(1, (target - (prev.cumNm ?? 0)) / span));
        if (t > 1e-6) {
          push(prev.lon + t * (p.lon - prev.lon), prev.lat + t * (p.lat - prev.lat));
        }
      }
      break;
    }
    if (p.jump) {
      flush();
      push(p.lon, p.lat);
      continue;
    }
    push(p.lon, p.lat);
  }
  flush();

  const parts = [];
  for (const coords of raw) {
    parts.push(...splitAntimeridianCoords(coords));
  }
  return parts;
}

/**
 * Reste à parcourir : de sailNm jusqu’à la fin (même découpe hops / antimeridien).
 * @returns {number[][][]} [lon, lat] parts
 */
export function remainingParts(flat, sailNm) {
  const pts = flat?.points || [];
  if (pts.length < 2) return [];
  const target = Math.max(0, Number(sailNm) || 0);
  const lastNm = pts[pts.length - 1].cumNm ?? 0;
  if (target >= lastNm - 1e-9) return [];
  const raw = [];
  let cur = [];

  const push = (lon, lat) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    cur.push([lon, lat]);
  };
  const flush = () => {
    if (cur.length >= 2) raw.push(cur);
    cur = [];
  };

  let started = false;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const cum = p.cumNm ?? 0;
    if (!started) {
      if (cum < target - 1e-9) continue;
      const prev = i > 0 ? pts[i - 1] : null;
      if (prev && cum > target + 1e-9 && !p.jump && !prev.jump) {
        const span = (cum - (prev.cumNm ?? 0)) || 1;
        const t = Math.max(0, Math.min(1, (target - (prev.cumNm ?? 0)) / span));
        push(prev.lon + t * (p.lon - prev.lon), prev.lat + t * (p.lat - prev.lat));
      }
      started = true;
    }
    if (p.jump) {
      flush();
      push(p.lon, p.lat);
      continue;
    }
    push(p.lon, p.lat);
  }
  flush();

  const parts = [];
  for (const coords of raw) {
    parts.push(...splitAntimeridianCoords(coords));
  }
  return parts;
}
