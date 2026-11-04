/**
 * Nœuds fond le long du trait : polaire brute × vent de mois.
 * kind: climatology. No GRIB, no POST /wind.
 */

import { trueWindAngle } from "./playSpeeds.js";
import { hasPolarRaw, polarBoatSpeed } from "./polarSpeed.js";
import { compactAtlasFields } from "../utils/atlasPoint.js";
import { boatSpeedFromWind, zoneWindAt } from "../utils/climatologyWind.js";

function roundKt(k) {
  const n = Number(k);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 10) / 10;
}

/**
 * @param {{
 *   lat: number,
 *   lon: number,
 *   bearing: number,
 *   month: number,
 *   polarRaw?: object | null,
 *   wind?: { speedKnots: number, dirFromDeg: number, kind?: string, model?: string, source?: string, reason?: string } | null,
 * }} args
 * @returns {{
 *   speedKnots: number,
 *   windKnots: number,
 *   twa: number | null,
 *   dirFromDeg: number,
 *   kind: string,
 *   source: string,
 *   model: string | null,
 *   reason: string | null,
 *   month: number,
 * }}
 */
export function alongTrackSpeed({ lat, lon, bearing, month, polarRaw = null, wind = null }) {
  const w = wind || zoneWindAt(lat, lon, month);
  const twa = trueWindAngle(bearing, w.dirFromDeg);
  let speed = null;
  if (hasPolarRaw(polarRaw) && twa != null) {
    speed = polarBoatSpeed(polarRaw, twa, w.speedKnots);
  }
  if (speed == null || !Number.isFinite(speed) || speed < 0) {
    speed = boatSpeedFromWind(w.speedKnots);
  }
  return {
    speedKnots: roundKt(speed) ?? boatSpeedFromWind(w.speedKnots),
    windKnots: roundKt(w.speedKnots) ?? 0,
    twa: twa == null ? null : Math.round(twa * 10) / 10,
    dirFromDeg: w.dirFromDeg,
    kind: w.kind || "climatology",
    source: w.source,
    model: w.model || null,
    reason: w.reason || null,
    month: Math.max(1, Math.min(12, Number(month) || 1)),
    ...compactAtlasFields(w),
  };
}
