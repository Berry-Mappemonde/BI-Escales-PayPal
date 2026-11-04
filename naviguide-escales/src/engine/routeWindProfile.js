/**
 * Samples along the track for the wind / knots mini-chart.
 * Start + stopovers + intermediate points, excluding air hops.
 */

const AIR_KINDS = new Set(["air", "plane", "flight"]);

export function routePoints(flat) {
  if (Array.isArray(flat)) return flat;
  return flat?.points || [];
}

function isAir(p) {
  if (!p) return false;
  if (p.jump) return true;
  return AIR_KINDS.has(p.kind);
}

function haversineNm(a, b) {
  const R = 3440.065;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const la1 = toRad(a.lat);
  const la2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Cap vrai 0–360 du segment a → b. */
export function bearingDeg(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const φ1 = toRad(a.lat);
  const φ2 = toRad(b.lat);
  const Δλ = toRad(b.lon - a.lon);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

export function twaDeg(headingDeg, windFromDeg) {
  const h = ((Number(headingDeg) % 360) + 360) % 360;
  const w = ((Number(windFromDeg) % 360) + 360) % 360;
  const raw = Math.abs(w - h);
  return raw > 180 ? 360 - raw : raw;
}

function pointAtCum(pts, cumNm) {
  if (!pts.length) return null;
  const target = Math.max(0, Number(cumNm) || 0);
  if (target <= (pts[0].cumNm ?? 0)) return pts[0];
  for (let i = 1; i < pts.length; i++) {
    if ((pts[i].cumNm ?? 0) >= target) return pts[i];
  }
  return pts[pts.length - 1];
}

function pointAtFilm(pts, filmNm) {
  if (!pts.length) return null;
  const target = Math.max(0, Number(filmNm) || 0);
  let best = pts[0];
  let bestD = Infinity;
  for (const p of pts) {
    const f = p.filmCum ?? p.cumNm ?? 0;
    const d = Math.abs(f - target);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return best;
}

function neighborAhead(pts, p) {
  const idx = pts.indexOf(p);
  if (idx < 0) return null;
  for (let i = idx + 1; i < pts.length; i++) {
    if (haversineNm(p, pts[i]) > 0.05) return pts[i];
  }
  return null;
}

/**
 * @returns {Array<{
 *   filmNm: number,
 *   cumNm: number,
 *   lat: number,
 *   lon: number,
 *   heading: number,
 *   kind: string,
 *   label: string,
 * }>}
 */
export function pickProfileSamples(flat, marks, { maxPoints = 24 } = {}) {
  const pts = routePoints(flat);
  if (pts.length < 2) return [];
  const last = pts[pts.length - 1];
  const maxFilm = last.filmCum ?? last.cumNm ?? 0;
  const maxCum = last.cumNm ?? 0;

  const wanted = new Map();
  const add = (filmNm, label, force) => {
    const p = pointAtFilm(pts, filmNm);
    if (!p || (!force && isAir(p))) return;
    const key = Math.round((p.filmCum ?? p.cumNm) * 10) / 10;
    if (wanted.has(key)) return;
    const nxt = neighborAhead(pts, p);
    const heading = nxt ? bearingDeg(p, nxt) : 0;
    wanted.set(key, {
      filmNm: p.filmCum ?? p.cumNm,
      cumNm: p.cumNm,
      lat: p.lat,
      lon: p.lon,
      heading,
      kind: isAir(p) ? "air" : (p.kind || "sail"),
      label: label || "",
    });
  };

  add(0, "Départ", true);
  for (const m of marks || []) {
    const kind = m.kind || "";
    if (kind.includes("air") || kind === "plane") continue;
    add(m.filmNm ?? m.nm, m.name, false);
  }
  add(maxFilm, "Arrivée", true);

  const budget = Math.max(0, maxPoints - wanted.size);
  if (budget > 0 && maxCum > 1) {
    const step = maxCum / (budget + 1);
    for (let i = 1; i <= budget; i++) {
      const p = pointAtCum(pts, step * i);
      if (p && !isAir(p)) add(p.filmCum ?? p.cumNm, "", false);
    }
  }

  return [...wanted.values()].sort((a, b) => a.filmNm - b.filmNm);
}

export function lerpSeries(samples, filmNm, key) {
  if (!samples?.length) return null;
  const x = Number(filmNm) || 0;
  if (x <= samples[0].filmNm) return samples[0][key] ?? null;
  const last = samples[samples.length - 1];
  if (x >= last.filmNm) return last[key] ?? null;
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1];
    const b = samples[i];
    if (x <= b.filmNm) {
      const span = b.filmNm - a.filmNm || 1;
      const t = (x - a.filmNm) / span;
      const av = a[key];
      const bv = b[key];
      if (av == null || bv == null) return av ?? bv ?? null;
      return av + (bv - av) * t;
    }
  }
  return last[key] ?? null;
}

export async function mapPool(items, limit, fn) {
  const list = items || [];
  const out = new Array(list.length);
  let i = 0;
  const workers = Math.max(1, Math.min(Number(limit) || 1, list.length || 1));
  async function worker() {
    while (i < list.length) {
      const idx = i;
      i += 1;
      out[idx] = await fn(list[idx], idx);
    }
  }
  await Promise.all(Array.from({ length: workers }, worker));
  return out;
}

export function cacheKeyLatLon(lat, lon, decimals = 2) {
  return `${Number(lat).toFixed(decimals)},${Number(lon).toFixed(decimals)}`;
}
