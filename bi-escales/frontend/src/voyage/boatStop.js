import { haversineNm } from "../../../../naviguide-escales/src/utils/geo.js";

const NEAR_BOAT_NM = 4;

/** Escale card to open when the user focuses the live boat (marker or judge chip). */
export function resolveBoatStop(stops, sample) {
  const list = stops || [];
  if (!list.length) return null;
  if (!sample) return list[0];

  let nearest = null;
  if (Number.isFinite(sample.lat) && Number.isFinite(sample.lon)) {
    let nearestNm = Infinity;
    for (const stop of list) {
      if (!Number.isFinite(stop.lat) || !Number.isFinite(stop.lon)) continue;
      const nm = haversineNm(sample.lat, sample.lon, stop.lat, stop.lon);
      if (nm < nearestNm) {
        nearestNm = nm;
        nearest = stop;
      }
    }
    if (nearest && nearestNm <= NEAR_BOAT_NM) return nearest;
  }

  if (sample.status === "waiting") {
    const saintMaur = list.find((stop) => /saint-maur/i.test(stop.name || ""));
    if (saintMaur) return saintMaur;
  }

  return nearest ?? list[0];
}
