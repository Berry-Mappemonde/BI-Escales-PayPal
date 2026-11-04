/** Rayon terrestre en milles nautiques. */
import { dropRepeatedStops } from "./escales.js";

export const R_NM = 3440.065;

export function toRad(deg) {
  return (deg * Math.PI) / 180;
}

/*
 * Longitudes : la seule implémentation côté client (même contrat que
 * server/longitude.py). Un repli écrit à la main ailleurs dans src/ est
 * refusé par src/utils/longitudeGuard.test.js.
 */

/** Replie dans [−180, 180] ; une valeur déjà dans l'intervalle est rendue telle quelle. */
export function wrapLon(lon) {
  if (!Number.isFinite(lon)) return lon;
  let x = lon;
  while (x > 180) x -= 360;
  while (x < -180) x += 360;
  return x;
}

/** Unwrap longitudes so the track does not cross the map at 180°. */
export function unwrapLon(prevLon, lon) {
  if (!Number.isFinite(lon)) return lon;
  if (!Number.isFinite(prevLon)) return lon;
  let x = lon;
  while (x - prevLon > 180) x -= 360;
  while (x - prevLon < -180) x += 360;
  return x;
}

/** Écart signé le plus court de `a` vers `b`, dans [−180, 180]. */
export function deltaLon(a, b) {
  return wrapLon(Number(b) - Number(a));
}

/**
 * Interpolation au plus court arc (t = 0 → a, t = 1 → b). Le résultat reste
 * déplié autour de `a` (−185 → −193 donne −189) : la carte peint sans saut.
 * Repliez avec wrapLon pour une API qui veut [−180, 180].
 */
export function lerpLon(a, b, t) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) {
    if (a == null || b == null) return a ?? b ?? null;
    return a + (b - a) * t;
  }
  return a + (unwrapLon(a, b) - a) * t;
}

function isLonLat(coordinate) {
  return Array.isArray(coordinate)
    && coordinate.length >= 2
    && Number.isFinite(Number(coordinate[0]))
    && Number.isFinite(Number(coordinate[1]));
}

/**
 * Déplie une ligne GeoJSON pour que 179° → −179° reste un petit trait Pacifique.
 * La géométrie résultante peut dépasser ±180° : Leaflet peut alors la peindre
 * sans traverser le globe.
 */
export function unwrapLineCoords(coords, firstLon = null) {
  const out = [];
  for (const coordinate of coords || []) {
    if (!isLonLat(coordinate)) continue;
    const lon = Number(coordinate[0]);
    const lat = Number(coordinate[1]);
    const previousLon = out.at(-1)?.[0] ?? firstLon;
    out.push([unwrapLon(previousLon, lon), lat]);
  }
  return out;
}

/** Déplie une polyligne relativement à *refLon* (aucun saut de 360°). */
export function unwrapPath(coords, refLon = null) {
  return unwrapLineCoords(coords, refLon);
}

export function haversineNm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(deltaLon(lon1, lon2));
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.sqrt(a));
}

/** Split a [lon,lat] polyline at ±180° (otherwise Leaflet draws across the globe). */
export function splitAntimeridianCoords(coords) {
  const parts = [[]];
  for (const c of coords || []) {
    if (!c || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) continue;
    const part = parts[parts.length - 1];
    if (part.length) {
      const prev = part[part.length - 1];
      if (Math.abs(c[0] - prev[0]) > 180) {
        parts.push([c]);
        continue;
      }
    }
    part.push(c);
  }
  return parts.filter((p) => p.length >= 2);
}

/**
 * Une polyligne dépliée (lon hors [−180, 180] après l'antiméridien), ramenée
 * dans [−180, 180] pour l'affichage et les exports : coupée au franchissement,
 * avec un point au bord (±180) de chaque côté. Le tracé carte garde la forme
 * dépliée ; seuls les fichiers et les textes reçoivent celle-ci.
 */
export function wrapLonParts(coords) {
  // Unfolded copy (no jump between neighbours), lat and extra values kept.
  const pts = [];
  for (const c of coords || []) {
    const lon = Number(c?.[0]);
    const lat = Number(c?.[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const u = pts.length ? unwrapLon(pts[pts.length - 1].u, lon) : lon;
    pts.push({ u, lat, extra: c.length > 2 ? c.slice(2) : [] });
  }
  if (!pts.length) return [];
  // A vertex exactly on ±180 belongs to the part in progress: the band
  // (copy of the world) comes from the first vertex off the edge.
  const onEdge = (u) => ((u + 180) % 360 + 360) % 360 === 0;
  const first = pts.find((p) => !onEdge(p.u)) || pts[0];
  let band = Math.round(first.u / 360);
  const parts = [];
  let part = [];
  let prev = null;
  for (const p of pts) {
    let rel = p.u - band * 360;
    // Cut only when the edge is strictly crossed.
    while (rel > 180 || rel < -180) {
      const edge = rel > 180 ? 180 : -180;
      const prevRel = prev ? prev.u - band * 360 : edge;
      const t = prev && rel !== prevRel ? (edge - prevRel) / (rel - prevRel) : 0;
      const edgeLat = prev ? prev.lat + (p.lat - prev.lat) * t : p.lat;
      const last = part[part.length - 1];
      if (!last || last[0] !== edge || last[1] !== edgeLat) part.push([edge, edgeLat]);
      if (part.length >= 2) parts.push(part);
      part = [[-edge, edgeLat]];
      band += edge > 0 ? 1 : -1;
      rel = p.u - band * 360;
    }
    part.push([rel, p.lat, ...p.extra]);
    prev = p;
  }
  if (part.length >= 2) parts.push(part);
  return parts;
}

/** Fenêtre navigable RA4 : une copie de chaque côté, pas l'infini. */
export const WORLD_COPY_LON_BOUND = 540;
/** 0, ±360, ±720 au plus — jamais une répétition infinie du monde. */
const MAX_WORLD_COPY_OFFSETS = 5;

function lonExtent(coords) {
  let minLon = Infinity;
  let maxLon = -Infinity;
  for (const coordinate of coords || []) {
    const lon = Number(coordinate?.[0]);
    if (!Number.isFinite(lon)) continue;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }
  return [minLon, maxLon];
}

function sortWorldCopyK(a, b) {
  if (a === 0) return -1;
  if (b === 0) return 1;
  if (a > 0 && b < 0) return -1;
  if (a < 0 && b > 0) return 1;
  return Math.abs(a) - Math.abs(b) || a - b;
}

/**
 * Décalages 360k pour qu'une ligne déjà dépliée recouvre [−bound, +bound].
 * Une ligne de ~360° produit souvent 0, ±360 et +720 (côté africain à droite).
 */
export function worldCopyOffsets(coords, lonBound = WORLD_COPY_LON_BOUND) {
  const [minLon, maxLon] = lonExtent(coords);
  if (!Number.isFinite(minLon)) return [0];
  const kLo = Math.ceil((-lonBound - maxLon) / 360);
  const kHi = Math.floor((lonBound - minLon) / 360);
  const ks = [];
  for (let k = kLo; k <= kHi; k += 1) ks.push(k);
  if (!ks.length) ks.push(0);
  if (ks.length > MAX_WORLD_COPY_OFFSETS) {
    ks.sort((a, b) => Math.abs(a) - Math.abs(b) || a - b);
    ks.length = MAX_WORLD_COPY_OFFSETS;
  }
  ks.sort(sortWorldCopyK);
  return ks.map((k) => k * 360);
}

/** Copies nécessaires pour couvrir la fenêtre navigable (±540°). */
export function worldCopyCoords(coords, lonBound = WORLD_COPY_LON_BOUND) {
  if (!coords || coords.length < 2) return [];
  return worldCopyOffsets(coords, lonBound).map((offset) => (
    offset === 0 ? coords : coords.map(([lon, lat]) => [lon + offset, lat])
  ));
}

/** Copies monde d'une ligne continue, y compris au franchissement de 180°. */
export function worldCopyLineCoords(coords) {
  return worldCopyCoords(unwrapLineCoords(coords));
}

/**
 * Trois copies d'un polygone GeoJSON. Chaque anneau est aligné sur l’anneau
 * extérieur avant décalage, afin de préserver trous et surfaces au Pacifique.
 */
export function worldCopyPolygonCoords(rings) {
  const outer = unwrapLineCoords(rings?.[0]);
  if (outer.length < 3) return [];
  const referenceLon = outer[0][0];
  const unwrappedRings = [
    outer,
    ...(rings || []).slice(1).map((ring) => unwrapLineCoords(ring, referenceLon)),
  ].filter((ring) => ring.length >= 3);
  return [0, 360, -360].map((offset) => (
    unwrappedRings.map((ring) => ring.map(([lon, lat]) => [lon + offset, lat]))
  ));
}

export function worldCopyLngs(lon, lonBound = WORLD_COPY_LON_BOUND) {
  const value = Number(lon);
  if (!Number.isFinite(value)) return [];
  return worldCopyOffsets([[value, 0], [value, 0]], lonBound).map((offset) => value + offset);
}

function uniqLngs(lngs) {
  const out = [];
  for (const lng of lngs) {
    if (!Number.isFinite(lng)) continue;
    if (out.every((x) => Math.abs(x - lng) > 1e-6)) out.push(lng);
  }
  return out;
}

/** Copies ±360° d'un point (lon brute + wrap), pour bateaux et drapeaux. */
export function markerCopyLngs(lon) {
  const x = Number(lon);
  if (!Number.isFinite(x)) return [];
  const wrapped = wrapLon(x);
  return uniqLngs([x, wrapped, x + 360, x - 360, wrapped + 360, wrapped - 360]);
}

/** Indice de copie monde, ancré sur wrap(lon) — stable si la lon source se déplie. */
export function worldCopyKey(lon, lng) {
  const base = wrapLon(lon);
  const x = Number(lng);
  if (!Number.isFinite(base) || !Number.isFinite(x)) return 0;
  return Math.round((x - base) / 360);
}

/** Écart (°) au-delà duquel on accepte de changer de copie (antiméridien). */
export const WORLD_COPY_HYSTERESIS_DEG = 80;

function nearestLng(copies, value) {
  return copies.reduce((best, v) => (Math.abs(v - value) < Math.abs(best - value) ? v : best));
}

/**
 * Copie monde sans saut : on garde la précédente tant que la caméra n'est pas
 * franchement plus proche d'une autre (Wallis / Nouméa au dézoom vers le centre).
 */
export function stabilizeWorldLng(lon, cameraLng, prevLng = null, hysteresisDeg = WORLD_COPY_HYSTERESIS_DEG) {
  const copies = markerCopyLngs(lon);
  if (!copies.length) return Number(lon);
  const cam = Number(cameraLng);
  const closest = Number.isFinite(cam) ? nearestLng(copies, cam) : copies[0];
  if (!Number.isFinite(Number(prevLng))) return closest;
  const prev = nearestLng(copies, Number(prevLng));
  if (!Number.isFinite(cam)) return prev;
  const hold = Number.isFinite(Number(hysteresisDeg)) ? Number(hysteresisDeg) : WORLD_COPY_HYSTERESIS_DEG;
  if (Math.abs(prev - cam) <= Math.abs(closest - cam) + hold) return prev;
  return closest;
}

/** Copies monde de chaque polyligne (décalages d'après l'étendue). */
export function worldCopyParts(parts) {
  const out = [];
  for (const coords of parts || []) {
    out.push(...worldCopyCoords(coords));
  }
  return out;
}

/**
 * Distance of a drawn route, leg by leg: the length the server gave for the
 * leg when there is one, otherwise the great-circle sum of its vertices.
 * The drawing box and the local briefing both use it, so they agree.
 */
export function legsDistanceNm(legs) {
  let nm = 0;
  for (const leg of legs || []) {
    if (!leg) continue;
    if (Number.isFinite(leg.nm)) {
      nm += leg.nm;
      continue;
    }
    const c = leg.coords || [];
    for (let i = 1; i < c.length; i++) nm += haversineNm(c[i - 1][1], c[i - 1][0], c[i][1], c[i][0]);
  }
  return nm;
}

/**
 * What the Expedition box shows: the distance through legsDistanceNm (the
 * length of each leg, as in the drawing box, the briefing and the export),
 * and the vertex segment count of summarizeRoute.
 */
export function routeStats(segments) {
  const { segments: count } = summarizeRoute(segments);
  return { nm: Math.round(legsDistanceNm(segments) * 10) / 10, segments: count };
}

/**
 * Distance nautique + nombre de segments d'une liste de polylignes
 * `segments` : [{ coords: [[lon, lat], ...] }]
 */
export function summarizeRoute(segments) {
  let nm = 0;
  let count = 0;
  if (!segments?.length) return { nm: 0, segments: 0 };
  for (const seg of segments) {
    const coords = seg?.coords;
    if (!coords || coords.length < 2) continue;
    // N sommets d'une polyligne → N − 1 segments.
    count += coords.length - 1;
    for (let i = 0; i < coords.length - 1; i++) {
      nm += haversineNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
    }
  }
  return { nm: Math.round(nm * 10) / 10, segments: count };
}

function segmentName(side) {
  return side?.name || "";
}

function segmentJoinsEscales(seg, fromName, toName) {
  const a = segmentName(seg?.from);
  const b = segmentName(seg?.to);
  return (a === fromName && b === toName) || (a === toName && b === fromName);
}

function legIsLand(from, to, segments) {
  const fromName = from?.name;
  const toName = to?.name;
  if (fromName && toName) {
    const hit = (segments || []).find((seg) => segmentJoinsEscales(seg, fromName, toName));
    if (hit) return Boolean(hit.nonMaritime);
  }
  return Boolean(from?.nonMaritime && to?.nonMaritime);
}

/**
 * Marques d'escale pour le résumé : une visite intérieure déjà vue
 * (Cayenne réinséré pour le HUD aérien) n'ajoute pas d'escale ; le
 * retour final qui reprend un nom déjà vu (La Rochelle) est gardé.
 */
export function marksForSummary(escaleMarks) {
  return dropRepeatedStops(escaleMarks);
}

function vertexCount(segments) {
  return (segments || []).reduce((count, seg) => count + (seg?.coords?.length ?? 0), 0);
}

function routerWaypointCount(segments) {
  return (segments || []).filter((seg) => seg?.coords?.length >= 2).length;
}

/**
 * Étapes entre escales (pas les sommets du routeur).
 * N points donnent N − 1 segments.
 */
export function summarizeLegs(escaleMarks, segments) {
  const segs = segments || [];
  const points = vertexCount(segs);
  const waypoints = routerWaypointCount(segs);
  const marks = marksForSummary(escaleMarks);

  if (marks.length >= 2) {
    let sea = 0;
    let land = 0;
    for (let i = 0; i < marks.length - 1; i++) {
      if (legIsLand(marks[i], marks[i + 1], segs)) land += 1;
      else sea += 1;
    }
    return {
      legs: marks.length - 1,
      sea,
      land,
      escales: marks.length,
      points,
      waypoints,
    };
  }

  // No marks (a drawn or imported route): one leg per segment between two
  // placed points, whatever the number of router vertices inside it.
  let sea = 0;
  let land = 0;
  for (const seg of segs) {
    const n = seg?.coords?.length ?? 0;
    if (n < 2) continue;
    if (seg.nonMaritime) land += 1;
    else sea += 1;
  }
  if (sea + land > 0) {
    return {
      legs: sea + land,
      sea,
      land,
      escales: marks.length,
      points,
      waypoints,
    };
  }

  return { legs: 0, sea: 0, land: 0, escales: marks.length, points, waypoints };
}

/** FeatureCollection LineString → segments { coords } pour summarizeRoute / export. */
export function featuresToSegments(fc) {
  if (!fc?.features) return [];
  return fc.features
    .filter((f) => f?.geometry?.type === "LineString" && f.geometry.coordinates?.length >= 2)
    .map((f) => ({
      coords: f.geometry.coordinates,
      from: { name: f.properties?.from || f.properties?.name || "" },
      to: { name: f.properties?.to || "" },
      nonMaritime: false,
      ...(Number.isFinite(f.properties?.nm) ? { nm: f.properties.nm } : {}),
    }));
}
