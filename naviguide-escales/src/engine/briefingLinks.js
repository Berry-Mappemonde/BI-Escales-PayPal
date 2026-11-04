import { localizePlaceName } from "../utils/placeNames.js";

/**
 * Briefing links — every place the ICI briefing names becomes clickable.
 * Pure functions. No HTTP. No chat.
 *
 * Two links per entity, in this order:
 *   1. "voir sur la carte" — the app switches the matching layer on and fits
 *      the map on the boat AND the place (handled by App / MapScene);
 *   2. the sheet — official site when the bag has one (Sextant, douane,
 *      marina website…), else a Google Maps sheet built from lat / lon.
 *
 * `segmentBriefing` never rewrites the text: it splits `narrateIci()` around
 * the names the bag already wrote, in order. Plain text stays identical.
 */
import { originName } from "./toponyms.js";

/** listPlaces() caps, mirrored from iciBriefing.js so we only link what is written. */
const WRITTEN = Object.freeze({
  poe: 4,
  amp: 3,
  project: 3,
  marina: 3,
  capitainerie: 2,
  wpi: 2,
  science: 3,
  anchorage: 3,
  aton: 3,
});

/** BI toggle (App `setShowBi*` / catalog id) to switch on for each kind. */
export const LAYER_FOR_KIND = Object.freeze({
  poe: "poe",
  amp: "amp",
  project: "projects",
  marina: "marinas",
  capitainerie: "capitaineries",
  wpi: "wpi",
  anchorage: "anchorages",
  aton: "aton",
  science: null, // decided by `source` (sextant, csr, argo, odatis, edmed)
});

const SCIENCE_LAYERS = new Set(["sextant", "csr", "argo", "odatis", "edmed"]);

/** Kinds that deserve a Google Maps sheet (a real place a skipper can go to). */
const MAPS_KINDS = new Set(["poe", "marina", "capitainerie", "wpi", "anchorage", "aton", "project"]);

/** null / undefined / "" stay unknown — Number(null) would lie with 0. */
function finite(n) {
  if (n == null || n === "") return null;
  return Number.isFinite(Number(n)) ? Number(n) : null;
}

function cleanUrl(url) {
  if (!url || typeof url !== "string") return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function googleMapsUrl(lat, lon) {
  const la = finite(lat);
  const lo = finite(lon);
  if (la == null || lo == null) return null;
  return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(5)}%2C${lo.toFixed(5)}`;
}

/** OSM seamark types → words a skipper reads (FR / EN). Unknown types keep their words. */
const ATON_WORDS = Object.freeze({
  light_major: ["phare", "lighthouse"],
  light_minor: ["feu", "minor light"],
  light: ["feu", "light"],
  light_vessel: ["bateau-feu", "light vessel"],
  buoy_lateral: ["bouée latérale", "lateral buoy"],
  buoy_cardinal: ["bouée cardinale", "cardinal buoy"],
  buoy_special_purpose: ["bouée spéciale", "special buoy"],
  buoy_safe_water: ["bouée d’eaux saines", "safe-water buoy"],
  buoy_isolated_danger: ["bouée de danger isolé", "isolated-danger buoy"],
  buoy_installation: ["bouée d’installation", "installation buoy"],
  beacon_lateral: ["balise latérale", "lateral beacon"],
  beacon_cardinal: ["balise cardinale", "cardinal beacon"],
  beacon_special_purpose: ["balise spéciale", "special beacon"],
  beacon_isolated_danger: ["balise de danger isolé", "isolated-danger beacon"],
  beacon_safe_water: ["balise d’eaux saines", "safe-water beacon"],
  landmark: ["amer", "landmark"],
  daymark: ["amer de jour", "daymark"],
  fog_signal: ["signal de brume", "fog signal"],
  radar_reflector: ["réflecteur radar", "radar reflector"],
  mooring: ["corps-mort", "mooring"],
});

/** "buoy_lateral" → "bouée latérale" ; a real name ("Fort Boyard") is untouched. */
export function humanAtonName(name, lang = "fr") {
  const raw = String(name || "").trim();
  if (!raw) return "";
  const key = raw.toLowerCase();
  if (ATON_WORDS[key]) return ATON_WORDS[key][lang === "en" ? 1 : 0];
  if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(key)) return key.replace(/_/g, " ");
  return raw;
}

/** Long dataset titles are cut so the briefing stays readable; the link keeps the whole sheet. */
export const DISPLAY_NAME_MAX = 72;
export function displayName(name, max = DISPLAY_NAME_MAX) {
  const s = String(name || "").replace(/\s+/g, " ").trim();
  if (s.length <= max) return s;
  const cut = s.slice(0, max - 1);
  const at = cut.lastIndexOf(" ");
  return `${at > max * 0.6 ? cut.slice(0, at) : cut}…`;
}

/** The name as the briefing writes it (same function on both sides, so links match). */
export function placeLabel(kind, item, lang = "fr") {
  const raw = kind === "aton" ? humanAtonName(item?.name, lang) : originName(item?.name);
  return displayName(localizePlaceName(raw, lang));
}

function entity(kind, item, index, lang) {
  if (!item || !item.name) return null;
  const url = cleanUrl(item.url) || (kind === "amp" ? cleanUrl(item.visit_url) || cleanUrl(item.manager_url) : null);
  return {
    id: `${kind}:${index}:${item.site_id ?? item.id ?? item.osm_id ?? item.name}`,
    kind,
    name: placeLabel(kind, item, lang),
    rawName: String(item.name),
    lat: finite(item.lat),
    lon: finite(item.lon),
    nm: finite(item.nm),
    url,
    source: item.source || null,
  };
}

/**
 * Entities in the order `narrateIci` writes them:
 * PoE → AMP → projects → marinas → capitaineries → WPI → science → anchorages → AtoN.
 */
export function briefingEntities(dossier, lang = "fr") {
  if (!dossier) return [];
  const out = [];
  const push = (kind, items) => {
    (items || []).slice(0, WRITTEN[kind]).forEach((it, i) => {
      const e = entity(kind, it, i, lang);
      if (e) out.push(e);
    });
  };
  push("poe", dossier.poe);
  push("amp", dossier.amp);
  push("project", dossier.projects);
  push("marina", dossier.nearby?.marinas);
  push("capitainerie", dossier.nearby?.capitaineries);
  push("wpi", dossier.nearby?.wpi);
  push("science", dossier.science?.nearby);
  push("anchorage", dossier.nearby?.anchorages);
  push("aton", dossier.aton?.nearby);
  return out;
}

/** Which BI layer to switch on so the place is drawn on the map. null = none. */
export function layerForEntity(e) {
  if (!e) return null;
  if (e.kind === "science") {
    const src = String(e.source || "").toLowerCase();
    return SCIENCE_LAYERS.has(src) ? src : null;
  }
  return LAYER_FOR_KIND[e.kind] ?? null;
}

/**
 * External sheets for an entity: official site first, Google Maps for real places.
 * `[{ kind: "site" | "maps", href, host }]`
 */
export function entityLinks(e) {
  if (!e) return [];
  const links = [];
  if (e.url) {
    let host = null;
    try { host = new URL(e.url).hostname.replace(/^www\./, ""); } catch { host = null; }
    links.push({ kind: e.kind === "source" ? "source" : "site", href: e.url, host });
  }
  if (MAPS_KINDS.has(e.kind)) {
    const maps = googleMapsUrl(e.lat, e.lon);
    if (maps) links.push({ kind: "maps", href: maps, host: "google.com/maps" });
  }
  return links;
}

/** A place can be focused on the map only with coordinates. */
export function canFocus(e) {
  return Boolean(e && e.lat != null && e.lon != null);
}

/**
 * Split the briefing text around entity names, sequentially (each entity is
 * searched after the previous match, so duplicates map to the right item).
 * Joining `segments.map(s => s.text)` gives back exactly `text`.
 */
export function segmentBriefing(text, entities) {
  const src = text || "";
  const segments = [];
  let cursor = 0;
  for (const e of entities || []) {
    if (!e?.name || e.name.length < 2) continue;
    const idx = src.indexOf(e.name, cursor);
    if (idx < 0) continue;
    if (idx > cursor) segments.push({ text: src.slice(cursor, idx) });
    segments.push({ text: e.name, entity: e });
    cursor = idx + e.name.length;
  }
  if (cursor < src.length) segments.push({ text: src.slice(cursor) });
  if (!segments.length && src) segments.push({ text: src });
  return segments;
}

/**
 * Source names the briefing may cite → official sheet.
 * Aliases (RTOFS, Copernicus, MarineRegions…) share the same URL so a
 * leftover phrase still becomes one link.
 */
export const SOURCE_URLS = Object.freeze({
  "Open-Meteo": "https://open-meteo.com/",
  "NOAA/RTOFS": "https://www.ncei.noaa.gov/products/weather-climate-models/rtofs",
  RTOFS: "https://www.ncei.noaa.gov/products/weather-climate-models/rtofs",
  EMODnet: "https://emodnet.ec.europa.eu/",
  GEBCO: "https://www.gebco.net/",
  "Copernicus Marine": "https://marine.copernicus.eu/",
  Copernicus: "https://marine.copernicus.eu/",
  "Marine Regions/VLIZ": "https://www.marineregions.org/",
  "Marine Regions": "https://www.marineregions.org/",
  MarineRegions: "https://www.marineregions.org/",
  OpenStreetMap: "https://www.openstreetmap.org/copyright",
  "douane.gouv.fr": "https://www.douane.gouv.fr/",
  CDSE: "https://dataspace.copernicus.eu/",
});

/** Canonical names listed here — each must produce a link when cited. */
export const KNOWN_SOURCES = Object.freeze([
  "Open-Meteo",
  "NOAA/RTOFS",
  "EMODnet",
  "GEBCO",
  "Copernicus Marine",
  "Marine Regions/VLIZ",
  "OpenStreetMap",
  "douane.gouv.fr",
  "CDSE",
]);

export function sourceEntity(name) {
  const url = SOURCE_URLS[name];
  if (!url) return null;
  return {
    id: `source:${name}`,
    kind: "source",
    name,
    rawName: name,
    lat: null,
    lon: null,
    nm: null,
    url,
    source: name,
  };
}

/** Longest names first so "Copernicus Marine" wins over "Copernicus". */
const SOURCE_NAMES = Object.freeze(
  Object.keys(SOURCE_URLS).sort((a, b) => b.length - a.length || a.localeCompare(b)),
);

export function sourceEntities() {
  return SOURCE_NAMES.map(sourceEntity).filter(Boolean);
}

/**
 * Split leftover briefing text around source names. Leftmost match wins;
 * at the same index the longer name wins (NOAA/RTOFS before RTOFS).
 */
export function segmentSources(text) {
  const src = text || "";
  const segments = [];
  let cursor = 0;
  while (cursor < src.length) {
    let best = null;
    for (const name of SOURCE_NAMES) {
      const idx = src.indexOf(name, cursor);
      if (idx < 0) continue;
      if (!best || idx < best.idx || (idx === best.idx && name.length > best.name.length)) {
        best = { idx, name };
      }
    }
    if (!best) {
      segments.push({ text: src.slice(cursor) });
      break;
    }
    if (best.idx > cursor) segments.push({ text: src.slice(cursor, best.idx) });
    segments.push({ text: best.name, entity: sourceEntity(best.name) });
    cursor = best.idx + best.name.length;
  }
  if (!segments.length && src) segments.push({ text: src });
  return segments;
}

/** Places first (sequential), then source names in the leftover spans. */
export function segmentBriefingWithSources(text, placeEntities) {
  const out = [];
  for (const seg of segmentBriefing(text, placeEntities)) {
    if (seg.entity) out.push(seg);
    else out.push(...segmentSources(seg.text));
  }
  return out;
}
