/** Teinte de la route parcourue. */
export const REGIME_COLORS = Object.freeze({
  hindcast: "#2dd4bf",
  forecast: "#38bdf8",
  climatology: "#c084fc",
});

function sameEraSpeed(a, b) {
  const left = Number(a);
  const right = Number(b);
  if (!Number.isFinite(left) && !Number.isFinite(right)) return true;
  if (!Number.isFinite(left) || !Number.isFinite(right)) return false;
  return Math.abs(left - right) < 0.05;
}

function mergeRegimeCoords(segs) {
  const out = [];
  for (const s of segs) {
    const last = out.at(-1);
    if (last && last.regime === s.regime && sameEraSpeed(last.speedKnots, s.speedKnots)) {
      last.coords.push(s.coords[1]);
    } else {
      out.push({ regime: s.regime, speedKnots: s.speedKnots, coords: s.coords.slice() });
    }
  }
  return out;
}

/** Vitesse hindcast d'époque, ou null (jamais inventée ; rien pour l'avion). */
export function traveledEraSpeed(segment) {
  if (!segment || segment.regime !== "hindcast") return null;
  if (segment.air || segment.vehicle === "plane" || segment.vehicle === "side") return null;
  const knots = Number(segment.speedKnots);
  if (!Number.isFinite(knots) || knots <= 0) return null;
  return Math.round(knots * 10) / 10;
}

/**
 * Tronçons de la route déjà parcourus, colorés par régime du pas courant.
 */
export function traveledRegimeSegments(vertices, traveledNm) {
  const limit = Number(traveledNm);
  const verts = Array.isArray(vertices) ? vertices : [];
  if (!Number.isFinite(limit) || limit <= 0 || verts.length < 2) return [];
  const raw = [];
  for (let i = 0; i < verts.length - 1; i++) {
    const a = verts[i];
    const b = verts[i + 1];
    if (!Number.isFinite(a?.lat) || !Number.isFinite(a?.lon)
      || !Number.isFinite(b?.lat) || !Number.isFinite(b?.lon)) continue;
    if (a.vehicle === "plane" || a.vehicle === "side"
      || b.vehicle === "plane" || b.vehicle === "side") continue;
    const aNm = Number(a.sailNm ?? a.filmNm ?? 0);
    const bNm = Number(b.sailNm ?? b.filmNm ?? 0);
    if (!(bNm > aNm + 1e-6)) continue;
    if (aNm >= limit) break;
    const endNm = Math.min(bNm, limit);
    const t = (endNm - aNm) / (bNm - aNm);
    const lat = a.lat + (b.lat - a.lat) * t;
    const lon = a.lon + (b.lon - a.lon) * t;
    raw.push({
      regime: b.regime || b.kind || a.regime || a.kind || "climatology",
      speedKnots: b.speedKnots ?? a.speedKnots ?? null,
      coords: [[a.lon, a.lat], [lon, lat]],
    });
  }
  return mergeRegimeCoords(raw);
}
