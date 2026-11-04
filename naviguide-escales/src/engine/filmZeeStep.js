import { wrapLon } from "../utils/geo.js";

/** One lookup per film step: 0.2° (~12 nm), not one request per frame. */
export const FILM_ZEE_STEP_DEG = 0.2;

export function filmZeeBucket(lat, lon, stepDeg = FILM_ZEE_STEP_DEG) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return "";
  const q = (n) => (Math.round(n / stepDeg) * stepDeg).toFixed(1);
  return `${q(la)}:${q(wrapLon(lo))}`;
}

/**
 * EEZ answer only when it was fetched for this film step.
 * A previous step (Adelaide, high seas) must not stay on screen
 * after the boat has moved to another bucket.
 */
export function filmZeeForBucket(zee, bucket) {
  if (!bucket || !zee || typeof zee !== "object") return null;
  if (zee.bucket !== bucket) return null;
  return zee;
}
