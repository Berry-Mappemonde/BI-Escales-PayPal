import { unwrapLon } from "../utils/geo.js";
import { isAirSegment } from "../utils/berryLegs.js";

/** Seuil inchangé : un clic à moins de 16 px du trait compte comme un clic route. */
export const ROUTE_CLICK_THRESHOLD_PX = 16;

/**
 * Distance en pixels du clic au segment le plus proche.
 * Le clic et chaque sommet sont ramenés dans la même copie du monde
 * (écart de longitude modulo 360) pour que le trait réponde à ±360°.
 */
export function pointToSegmentPx(map, lat, lon, coords) {
  const point = map.latLngToLayerPoint([lat, lon]);
  let best = Infinity;
  for (let index = 0; index < coords.length - 1; index += 1) {
    const [lon1, lat1] = coords[index];
    const [lon2, lat2] = coords[index + 1];
    const from = map.latLngToLayerPoint([lat1, unwrapLon(lon, lon1)]);
    const to = map.latLngToLayerPoint([lat2, unwrapLon(lon, lon2)]);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const lengthSq = dx * dx + dy * dy;
    const ratio = lengthSq
      ? Math.max(0, Math.min(1, ((point.x - from.x) * dx + (point.y - from.y) * dy) / lengthSq))
      : 0;
    best = Math.min(best, Math.hypot(point.x - (from.x + ratio * dx), point.y - (from.y + ratio * dy)));
  }
  return best;
}

export function isNearRoute(map, lat, lon, segments, thresholdPx = ROUTE_CLICK_THRESHOLD_PX) {
  return (segments || []).some((segment) => (
    !isAirSegment(segment)
    && segment.coords?.length > 1
    && pointToSegmentPx(map, lat, lon, segment.coords) < thresholdPx
  ));
}
