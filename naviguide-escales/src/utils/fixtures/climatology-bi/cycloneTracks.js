/** IBTrACS traces: unwrap into one polyline, then copy ±360°. Never cut at 180°. */

function isLonLat(c) {
  return Array.isArray(c) && c.length >= 2 && Number.isFinite(Number(c[0])) && Number.isFinite(Number(c[1]));
}

function unwrapLon(prevLon, lon) {
  let x = Number(lon);
  if (!Number.isFinite(x) || !Number.isFinite(prevLon)) return x;
  while (x - prevLon > 180) x -= 360;
  while (x - prevLon < -180) x += 360;
  return x;
}

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

function worldCopyCoords(coords) {
  if (!coords || coords.length < 2) return [];
  return [
    coords,
    coords.map(([lon, lat]) => [lon + 360, lat]),
    coords.map(([lon, lat]) => [lon - 360, lat]),
  ];
}

/** GeoJSON [lon, lat][] → Leaflet [lat, lng][][] (1 line × 3 world copies). */
export function cycloneLatLngCopies(coordinates) {
  const u = unwrapCycloneCoords(coordinates);
  if (u.length < 2) return [];
  return worldCopyCoords(u).map((copy) => copy.map(([lon, lat]) => [lat, lon]));
}

/** Reassemble split API parts of the same sid before unwrap. */
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
