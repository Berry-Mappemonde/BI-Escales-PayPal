import { haversineNm } from "../../../../naviguide-escales/src/utils/geo.js";

const KM_TO_NM = 1 / 1.852;

/**
 * Projets proches d’une escale (filtre carte). Copie du motif MarinasPanel + haversine NAVIGUIDE.
 */
export function projectsNearRoute(features, stops, { maxKm = 200, limit = 50 } = {}) {
  const list = Array.isArray(features) ? features : [];
  if (!list.length) return [];
  if (!Array.isArray(stops) || !stops.length) return list.slice(0, limit);
  const maxNm = maxKm * KM_TO_NM;
  const ranked = list
    .map((feature) => {
      const [lon, lat] = feature.geometry?.coordinates || [];
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return { feature, distance: Infinity };
      let distance = Infinity;
      for (const stop of stops) {
        const d = haversineNm(lat, lon, stop.lat, stop.lon);
        if (d < distance) distance = d;
      }
      return { feature, distance };
    })
    .filter((row) => row.distance <= maxNm)
    .sort((a, b) => a.distance - b.distance);
  return ranked.slice(0, limit).map((row) => row.feature);
}
