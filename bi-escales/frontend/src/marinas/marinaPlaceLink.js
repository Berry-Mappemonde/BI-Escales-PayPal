/**
 * Google Maps /place/ link guard for stopover marinas.
 * Logic adapted from Blue-Intelligence-V3 ``marina_maps_place.py``
 * (``NON_MARINA_RE``, ``place_coords``, ``haversine_m``, ``is_google_place_url``).
 */
import { haversineNm } from "../../../../naviguide-escales/src/utils/geo.js";

export const MAX_PLACE_DISTANCE_M = 1000;

const PLACE_PATH_RE = /\/maps\/place\//i;
const SEARCH_PATH_RE = /\/maps\/search\//i;
const COORDS_RE = /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/;
const DATA_COORDS_RE = /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/;

/** Same intent as ``marina_maps_place.NON_MARINA_RE`` plus driving schools (Clément 19:43). */
export const SUSPICIOUS_PLACE_RE =
  /\b(auto[\s-]?[ée]coles?|bateaux?[\s-]?[ée]coles?|driving\s+school|restaurant|hotel|hôtel|pizzeria|café|cafe|brasserie|nightclub|bar)\b/i;

export function googleMapsSearchUrl(lat, lon) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
  return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(5)}%2C${lo.toFixed(5)}`;
}

export function isGooglePlaceUrl(url) {
  const raw = String(url || "").trim();
  if (!raw.startsWith("http")) return false;
  if (SEARCH_PATH_RE.test(raw)) return false;
  try {
    const host = new URL(raw).hostname.toLowerCase();
    if (!host.includes("google.")) return false;
  } catch {
    return false;
  }
  return PLACE_PATH_RE.test(raw);
}

export function placeCoordsFromUrl(url) {
  const raw = decodeURIComponent(String(url || ""));
  const match = raw.match(COORDS_RE) || raw.match(DATA_COORDS_RE);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon };
}

export function placeSlugFromUrl(url) {
  try {
    const parts = decodeURIComponent(new URL(url).pathname).split("/").filter(Boolean);
    const idx = parts.findIndex((p) => p.toLowerCase() === "place");
    if (idx < 0 || idx + 1 >= parts.length) return "";
    return parts[idx + 1].replace(/\+/g, " ");
  } catch {
    return "";
  }
}

export function haversineM(lat1, lon1, lat2, lon2) {
  return haversineNm(lat1, lon1, lat2, lon2) * 1852;
}

/**
 * @returns {{ safePlace: boolean, mapsLink: string|null, rejectedReason: string|null }}
 */
export function evaluateGooglePlaceLink(marina) {
  const lat = Number(marina?.lat);
  const lon = Number(marina?.lon);
  const search = googleMapsSearchUrl(lat, lon);
  const candidate =
    marina?.maps_place_url ||
    (isGooglePlaceUrl(marina?.maps_url) ? marina.maps_url : null) ||
    (isGooglePlaceUrl(marina?.maps_link) ? marina.maps_link : null);

  if (!candidate) {
    return { safePlace: false, mapsLink: search, rejectedReason: null };
  }

  const slug = placeSlugFromUrl(candidate);
  const blob = `${slug} ${decodeURIComponent(candidate)}`;
  if (SUSPICIOUS_PLACE_RE.test(blob)) {
    return { safePlace: false, mapsLink: search, rejectedReason: "suspicious_name" };
  }

  const coords = placeCoordsFromUrl(candidate);
  if (coords && Number.isFinite(lat) && Number.isFinite(lon)) {
    if (haversineM(lat, lon, coords.lat, coords.lon) > MAX_PLACE_DISTANCE_M) {
      return { safePlace: false, mapsLink: search, rejectedReason: "distance" };
    }
  }

  return { safePlace: true, mapsLink: candidate, rejectedReason: null };
}

export function applyMarinaPlacePolicy(marina) {
  const ev = evaluateGooglePlaceLink(marina);
  return {
    ...marina,
    maps_url: ev.mapsLink,
    safe_google_place: ev.safePlace,
    maps_place_rejected: ev.rejectedReason,
  };
}

export function summarizePlaceSafety(marinas) {
  let safe = 0;
  let rejected = 0;
  for (const marina of marinas || []) {
    const hadPlace = isGooglePlaceUrl(
      marina?.maps_place_url || marina?.maps_url || marina?.maps_link,
    );
    if (!hadPlace) continue;
    const ev = evaluateGooglePlaceLink(marina);
    if (ev.safePlace) safe += 1;
    else rejected += 1;
  }
  return { safe, rejected };
}
