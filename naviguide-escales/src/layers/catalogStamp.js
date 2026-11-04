// Pure helpers of the catalog layer (no Leaflet): testable in Node.

/** Vertex count and extent of any GeoJSON coordinates (no copy, no JSON). */
function coordsExtent(coords, acc = { n: 0, w: Infinity, s: Infinity, e: -Infinity, nn: -Infinity }) {
  if (!Array.isArray(coords)) return acc;
  if (typeof coords[0] === "number") {
    const [lon, lat] = coords;
    acc.n += 1;
    if (lon < acc.w) acc.w = lon;
    if (lon > acc.e) acc.e = lon;
    if (lat < acc.s) acc.s = lat;
    if (lat > acc.nn) acc.nn = lat;
    return acc;
  }
  for (const c of coords) coordsExtent(c, acc);
  return acc;
}

/**
 * What a drawn feature depends on. A point's radius follows the zoom, so the
 * zoom step is part of it: a point kept across a zoom is drawn again.
 * A shape is known by its id, its vertex count and its extent.
 */
export function featureStamp(feature, zoom) {
  const properties = feature?.properties || {};
  const geometry = feature?.geometry || {};
  if (geometry.type === "Point") {
    const [lon, lat] = geometry.coordinates || [];
    const z = Number.isFinite(Number(zoom)) ? Math.round(Number(zoom)) : "";
    return `${properties.naviguideCatalogId}|${properties.clusterCount || 1}|${lon}|${lat}|z${z}`;
  }
  const x = coordsExtent(geometry.coordinates);
  return `${properties.naviguideCatalogId}|${geometry.type}|${x.n}|${x.w},${x.s},${x.e},${x.nn}`;
}

/**
 * Whether the catalog pick may take this click. Controls, markers, popups,
 * the briefing highlight and other interactive vector layers keep theirs.
 */
export function catalogMayTakeClick(target) {
  if (!target || typeof target.closest !== "function") return false;
  if (target.closest(".leaflet-control, .leaflet-marker-icon, .leaflet-popup, .leaflet-briefing-focus-pane")) return false;
  // An SVG path of another layer (route, highlight) under the pointer.
  if (target.closest("path.leaflet-interactive, svg .leaflet-interactive")) return false;
  return true;
}

/** Removes the map's catalog click listener once no catalog layer is left on it. */
export function releaseCatalogPick(map, layers) {
  if (!map?._biCatalogPick) return false;
  for (const layer of layers || []) if (layer.map === map) return false;
  map.getContainer?.()?.removeEventListener("click", map._biCatalogPick, true);
  map._biCatalogPick = null;
  return true;
}
