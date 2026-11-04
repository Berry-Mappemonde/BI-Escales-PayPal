import { featureContains } from "../utils/layerIdentify.js";

/** Tolérance canvas Leaflet (px) ajoutée au rayon du point. */
export const CATALOG_HIT_TOLERANCE_PX = 8;
const LON_SHIFTS = [-720, -360, 0, 360, 720];

/**
 * Rayon cliquable d'un point catalogue.
 * Même portée que le cercle canvas : rayon « pointe » + demi-trait + tolérance.
 */
export function catalogPointRadiusPx(zoom, clusterCount = 1) {
  const z = Number(zoom) || 2;
  let radius = 0.7;
  if (z > 3) radius = 0.95;
  if (z > 5) radius = 1.25;
  if (z > 8) radius = 1.8;
  if (z > 12) radius = 2.4;
  const count = Number(clusterCount) || 1;
  const bump = count > 1 ? Math.min(6, Math.log2(count)) : 0;
  return Math.max(0.55, radius + bump) + 0.5 + CATALOG_HIT_TOLERANCE_PX;
}

export function isClusterFeature(feature) {
  return Number(feature?.properties?.clusterCount) > 1;
}

function segmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 > 0
    ? Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / len2))
    : 0;
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy));
}

function pointHits(feature, lat, lon, project, radiusPx) {
  const [featureLon, featureLat] = feature?.geometry?.coordinates || [];
  if (!Number.isFinite(featureLon) || !Number.isFinite(featureLat)) return false;
  const click = project(lon, lat);
  if (!click) return false;
  return LON_SHIFTS.some((shift) => {
    const projected = project(featureLon + shift, featureLat);
    return projected && Math.hypot(projected.x - click.x, projected.y - click.y) <= radiusPx;
  });
}

function polygonHits(feature, lat, lon) {
  return LON_SHIFTS.some((shift) => featureContains(feature, lon + shift, lat));
}

function lineHits(feature, lat, lon, project, radiusPx) {
  const geometry = feature?.geometry || {};
  const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
  const click = project(lon, lat);
  if (!click || !lines) return false;
  return lines.some((line) => LON_SHIFTS.some((shift) => {
    for (let index = 1; index < (line || []).length; index += 1) {
      const start = project(line[index - 1][0] + shift, line[index - 1][1]);
      const end = project(line[index][0] + shift, line[index][1]);
      if (start && end && segmentDistance(click, start, end) <= radiusPx) return true;
    }
    return false;
  }));
}

export function featureHitsClick(feature, lat, lon, project, radiusPx) {
  const type = feature?.geometry?.type;
  if (type === "Point") return pointHits(feature, lat, lon, project, radiusPx);
  if (type === "Polygon" || type === "MultiPolygon") return polygonHits(feature, lat, lon);
  if (type === "LineString" || type === "MultiLineString") return lineHits(feature, lat, lon, project, radiusPx);
  return false;
}

/**
 * Objet le plus haut sous le clic.
 * `z` est le pan (l'AMP passe devant les points), `order` départage un même pan.
 */
export function pickCatalogHit(entries, lat, lon, project) {
  let best = null;
  (entries || []).forEach((entry) => {
    if (!featureHitsClick(entry.feature, lat, lon, project, entry.radiusPx)) return;
    if (
      !best
      || entry.z > best.z
      || (entry.z === best.z && entry.order > best.order)
    ) best = entry;
  });
  return best;
}

export function ficheFromHit(hit, lat, lon) {
  if (!hit) return null;
  return {
    lon,
    lat,
    kind: hit.kind,
    props: hit.feature?.properties || {},
  };
}
