import { unwrapLon, worldCopyCoords } from "../utils/geo.js";
import { worldCopyLngs } from "../utils/gribSymbols.js";

/**
 * Trois longitudes (0 / +360 / −360) pour que l’atlas tienne
 * sur la copie Pacifique près de 180°, pas seulement sur [-180, 180].
 */
export function climoPointLngs(lon) {
  return worldCopyLngs(lon);
}

function isLonLat(c) {
  return Array.isArray(c) && c.length >= 2 && Number.isFinite(Number(c[0])) && Number.isFinite(Number(c[1]));
}

/** Unwrap so 170 → −170 becomes 170 → 190 (one continuous Pacific line). */
export function unwrapCycloneCoords(coordinates) {
  const out = [];
  for (const c of coordinates || []) {
    if (!isLonLat(c)) continue;
    const lon = Number(c[0]);
    const lat = Number(c[1]);
    if (!out.length) out.push([lon, lat]);
    else out.push([unwrapLon(out[out.length - 1][0], lon), lat]);
  }
  return out;
}

/**
 * Une tempête = une polyligne unwrap, puis copies monde ±360°.
 * Ne jamais couper à 180° : Leaflet doit voir 170 → 185 → 190.
 * Entrée GeoJSON [lon, lat][]. Sortie Leaflet [lat, lng][][].
 */
export function cycloneLatLngCopies(coordinates) {
  const u = unwrapCycloneCoords(coordinates);
  if (u.length < 2) return [];
  return worldCopyCoords(u).map((copy) => copy.map(([lon, lat]) => [lat, lon]));
}

/** Backend may emit several LineStrings for one sid. Reassemble in order. */
export function groupCycloneFeatures(features) {
  const groups = [];
  const index = new Map();
  for (const f of features || []) {
    const coords = f?.geometry?.coordinates;
    if (!Array.isArray(coords) || coords.length < 2) continue;
    const sid = f?.properties?.sid;
    if (sid && index.has(sid)) {
      index.get(sid).coords.push(...coords);
      continue;
    }
    const g = { properties: f.properties || {}, coords: coords.slice() };
    groups.push(g);
    if (sid) index.set(sid, g);
  }
  return groups;
}
