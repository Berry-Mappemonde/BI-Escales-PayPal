import { sampleClockAtTime } from "../engine/voyageClock.js";
import { wrapLon } from "../utils/geo.js";

/** HUD GRIB : pas de message « absente » avant un fetch autour du bateau. */

/** Query GRIB : horloge officielle + lon wrappée. Pas l’horloge locale sans polar. */
export function officialGribQuery(clock, when = new Date()) {
  const sample = clock ? sampleClockAtTime(clock, when) : null;
  if (sample?.lat == null || sample?.lon == null) return null;
  const lon = wrapLon(sample.lon);
  if (!Number.isFinite(Number(sample.lat)) || !Number.isFinite(lon)) return null;
  return { lat: sample.lat, lon };
}


export function officialGribStatus({ enabled, grib, pending, positioned } = {}) {
  if (!enabled) return null;
  if (grib?.status === "ready") return "ready";
  if (pending || grib?.status === "pending" || grib?.refreshing || !positioned || !grib) return "pending";
  return "absent";
}

export function officialGribWarning({ enabled, status } = {}) {
  if (!enabled || status !== "absent") return null;
  return "dernière prévision absente";
}
