import {
  FILM_BOAT_KEEP_FRAC,
  FILM_PAN_MAX_SCREEN,
  FILM_RESET_EVERY,
  FILM_ZOOM_MAX,
  FILM_ZOOM_MIN,
} from "../engine/replay.js";
import { haversineNm, lerpLon, unwrapLon } from "../utils/geo.js";

/** Horloge UI React : assez pour la barre, trop rare pour faire sauter la caméra. */
export const FILM_UI_MS = 80;
/** La pose affichée est en retard d'un cran : on interpole entre deux échantillons. */
export const FILM_INTERP_DELAY_MS = 80;
/** Au-delà, une tuile manquante ralentit le pan (évite le damier gris). */
export const FILM_TILE_READY_MIN = 0.7;
export const FILM_TILE_SLOW = 0.35;

/** Jambe plus courte que ça : un seul cadre pour tout le chapitre.
 * 280 nm couvre Fort-de-France → Marigot (~238 nm) sans prendre une traversée. */
export const FILM_ARCHIPELAGO_NM = 280;
export const FILM_ZOOM_ARCHIPELAGO_MAX = 5;
/** Un pas bateau plus grand que ça (px / frame) = ancre, pas la glisse.
 * 80 px : un hitch ~54 px (VL / 180 px·s⁻¹ × 0,3 s) n'est plus classé ancre. */
export const FILM_INTRA_JUMP_PX = 80;
/** Hors zoom et hors flip : aucun pas écran bateau / caméra > 30 px. */
export const FILM_SCREEN_STEP_MAX_PX = 30;
/** Après un saut d'ancre, on ne recadre que si le bateau quitte ~l'écran. */
export const FILM_VIEWPORT_KEEP_FRAC = 0.8;

function toLatLngPair(v) {
  if (!v) return null;
  if (Array.isArray(v)) {
    const lat = Number(v[0]);
    const lon = Number(v[1]);
    return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
  }
  const lat = Number(v.lat);
  const lon = Number(v.lng ?? v.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
}

function mapSize(map) {
  const size = typeof map?.getSize === "function" ? map.getSize() : { x: 1280, y: 800 };
  return { x: Number(size?.x) || 1280, y: Number(size?.y) || 800 };
}

/** Décale le centre pour que le bateau reste dans le cadre `keepFrac` (40 % centraux). */
export function keepBoatInFrame(center, boat, map, { keepFrac = FILM_BOAT_KEEP_FRAC } = {}) {
  const c = toLatLngPair(center);
  const b = toLatLngPair(boat);
  if (!c || !b || typeof map?.latLngToContainerPoint !== "function" || typeof map?.containerPointToLatLng !== "function") {
    return center;
  }
  const size = mapSize(map);
  const maxX = size.x * keepFrac * 0.5;
  const maxY = size.y * keepFrac * 0.5;
  const boatPt = map.latLngToContainerPoint(b);
  const centerPt = map.latLngToContainerPoint(c);
  const dx = (boatPt.x ?? 0) - (centerPt.x ?? 0);
  const dy = (boatPt.y ?? 0) - (centerPt.y ?? 0);
  let extraX = 0;
  let extraY = 0;
  if (dx > maxX) extraX = dx - maxX;
  else if (dx < -maxX) extraX = dx + maxX;
  if (dy > maxY) extraY = dy - maxY;
  else if (dy < -maxY) extraY = dy + maxY;
  if (!extraX && !extraY) return c;
  const ll = map.containerPointToLatLng({ x: (centerPt.x ?? 0) + extraX, y: (centerPt.y ?? 0) + extraY });
  return [ll.lat, ll.lng ?? ll.lon];
}

/**
 * Borne un déplacement carte (lat/lon) à `maxPx` à l'écran.
 * Un `setView` / `keepBoatInFrame` / pan trop long est rejeté : on avance
 * d'au plus 30 px. Flip et premier calage n'appellent pas ceci.
 */
export function clampFilmScreenStep(map, from, to, maxPx = FILM_SCREEN_STEP_MAX_PX) {
  const a = toLatLngPair(from);
  const b = toLatLngPair(to);
  if (!a || !b) return to;
  const cap = Math.max(1, Number(maxPx) || FILM_SCREEN_STEP_MAX_PX);
  if (typeof map?.latLngToContainerPoint !== "function" || typeof map?.containerPointToLatLng !== "function") {
    return b;
  }
  const p0 = map.latLngToContainerPoint(a);
  const p1 = map.latLngToContainerPoint(b);
  const dx = (p1.x ?? 0) - (p0.x ?? 0);
  const dy = (p1.y ?? 0) - (p0.y ?? 0);
  const dist = Math.hypot(dx, dy);
  if (!(dist > cap)) return b;
  const s = cap / dist;
  const ll = map.containerPointToLatLng({ x: p0.x + dx * s, y: p0.y + dy * s });
  return [ll.lat, ll.lng ?? ll.lon];
}

/**
 * Borne un pas de caméra : assez grand pour suivre le bateau (vitesse),
 * et toujours assez pour le garder dans les 40 % centraux.
 */
export function clampFilmPan(from, to, map, {
  maxFrac = FILM_PAN_MAX_SCREEN,
  boat = null,
  keepFrac = FILM_BOAT_KEEP_FRAC,
} = {}) {
  const a = toLatLngPair(from);
  const b = toLatLngPair(to);
  if (!a || !b) return to;
  const size = mapSize(map);
  const maxPx = Math.max(1, size.x * maxFrac);
  let limited = b;
  if (typeof map?.latLngToContainerPoint === "function" && typeof map?.containerPointToLatLng === "function") {
    const p0 = map.latLngToContainerPoint(a);
    const p1 = map.latLngToContainerPoint(b);
    const dx = (p1.x ?? 0) - (p0.x ?? 0);
    const dy = (p1.y ?? 0) - (p0.y ?? 0);
    const dist = Math.hypot(dx, dy);
    if (dist > maxPx) {
      const s = maxPx / dist;
      const ll = map.containerPointToLatLng({ x: p0.x + dx * s, y: p0.y + dy * s });
      limited = [ll.lat, ll.lng ?? ll.lon];
    }
  } else if (typeof map?.getBounds === "function") {
    try {
      const bounds = map.getBounds();
      const widthDeg = Math.abs(bounds.getEast() - bounds.getWest()) || 1;
      const maxDeg = widthDeg * maxFrac;
      const dLat = b[0] - a[0];
      const dLon = b[1] - a[1];
      const dist = Math.hypot(dLat, dLon);
      if (dist > maxDeg) {
        const s = maxDeg / dist;
        limited = [a[0] + dLat * s, a[1] + dLon * s];
      }
    } catch { /* fake map */ }
  }
  const kept = keepBoatInFrame(limited, boat || b, map, { keepFrac });
  const cap = Math.min(FILM_SCREEN_STEP_MAX_PX, maxPx);
  return clampFilmScreenStep(map, a, kept, cap);
}

/** Zoom fixe d'un chapitre : la jambe tient dans ~70 % de la fenêtre, borné [3 ; 7]. */
function finiteCoord(v) {
  return v != null && v !== "" && Number.isFinite(Number(v));
}

export function filmLegSpanNm(leg) {
  const aLat = Number(leg?.fromLat);
  const aLon = Number(leg?.fromLon);
  const bLat = Number(leg?.toLat);
  const bLon = Number(leg?.toLon);
  if (![aLat, aLon, bLat, bLon].every(Number.isFinite)) return null;
  return haversineNm(aLat, aLon, bLat, bLon);
}

export function filmLegIsArchipelago(leg) {
  const span = filmLegSpanNm(leg);
  return Number.isFinite(span) && span > 0 && span <= FILM_ARCHIPELAGO_NM;
}

/** Centre du cadre de jambe (milieu from→to), pas une île ni une bouée. */
export function filmChapterCenter(leg) {
  const aLat = Number(leg?.fromLat);
  const aLon = Number(leg?.fromLon);
  const bLat = Number(leg?.toLat);
  const bLon = Number(leg?.toLon);
  if (![aLat, aLon, bLat, bLon].every(Number.isFinite)) return null;
  return [(aLat + bLat) / 2, lerpLon(aLon, bLon, 0.5)];
}

/**
 * En pleine jambe : la caméra traduit avec le bateau
 * (`clampFilmPan` / delta bateau), y compris une jambe archipel (≤ 280 nm).
 * Un saut d'ancre (bouée, île, événement) déplace le bateau, pas le centre,
 * sauf si le bateau sortirait de l'écran (`FILM_INTRA_JUMP_PX`).
 * `filmLeg` sert au seuil d'archipel ailleurs (zoom) ; ici plus de cadre figé.
 */
export function filmIntraChapterCenter(map, {
  from,
  boat,
  lastBoat = null,
  filmLeg: _filmLeg = null,
  maxFrac = FILM_PAN_MAX_SCREEN,
  boatPx = 0,
} = {}) {
  const origin = toLatLngPair(from) || toLatLngPair(boat);
  const here = toLatLngPair(boat);
  if (!origin || !here) return boat;
  let stepPx = Number(boatPx) || 0;
  const prev = lastBoatPair(lastBoat);
  if (prev && typeof map?.latLngToContainerPoint === "function") {
    const a = map.latLngToContainerPoint(prev);
    const b = map.latLngToContainerPoint(here);
    stepPx = Math.hypot((b.x ?? 0) - (a.x ?? 0), (b.y ?? 0) - (a.y ?? 0));
  }
  if (stepPx > FILM_INTRA_JUMP_PX) {
    const kept = keepBoatInFrame(origin, here, map, { keepFrac: FILM_VIEWPORT_KEEP_FRAC });
    return clampFilmScreenStep(map, origin, kept, FILM_SCREEN_STEP_MAX_PX);
  }
  if (!prev) {
    return clampFilmPan(origin, here, map, {
      maxFrac,
      boat: here,
      keepFrac: FILM_BOAT_KEEP_FRAC,
    });
  }
  const followed = [
    origin[0] + (here[0] - prev[0]),
    origin[1] + (unwrapLon(prev[1], here[1]) - prev[1]),
  ];
  return clampFilmPan(origin, followed, map, {
    maxFrac,
    boat: here,
    keepFrac: FILM_BOAT_KEEP_FRAC,
  });
}

export function filmChapterZoom(map, leg, { min = FILM_ZOOM_MIN, max = FILM_ZOOM_MAX } = {}) {
  const aLat = Number(leg?.fromLat);
  const aLon = Number(leg?.fromLon);
  const bLat = Number(leg?.toLat);
  const bLon = Number(leg?.toLon);
  if (!map || ![leg?.fromLat, leg?.fromLon, leg?.toLat, leg?.toLon].every(finiteCoord)) {
    return Math.max(min, Math.min(max, 5));
  }
  const spanNm = filmLegSpanNm(leg);
  const shortHop = Number.isFinite(spanNm) && spanNm > 0 && spanNm <= FILM_ARCHIPELAGO_NM;
  const cap = shortHop ? Math.min(max, FILM_ZOOM_ARCHIPELAGO_MAX) : max;
  let z = 5;
  try {
    let bounds = [[aLat, aLon], [bLat, bLon]];
    if (shortHop) {
      const padDeg = 2.5;
      const midLat = (aLat + bLat) / 2;
      const midLon = (aLon + bLon) / 2;
      bounds = [
        [midLat - padDeg, midLon - padDeg],
        [midLat + padDeg, midLon + padDeg],
      ];
    }
    const size = typeof map.getSize === "function" ? map.getSize() : null;
    const pad = size && Number.isFinite(size.x)
      ? [size.y * 0.15, size.x * 0.15]
      : [72, 96];
    if (typeof map.getBoundsZoom === "function") {
      z = map.getBoundsZoom(bounds, false, pad);
    }
  } catch { /* fake map in tests */ }
  if (!Number.isFinite(z)) z = 5;
  return Math.max(min, Math.min(cap, z));
}

/** Cap lissé de la jambe : moyenne circulaire des derniers échantillons. */
export function smoothFilmHeading(samples, fallback = 0, { max = 8 } = {}) {
  const list = samples || [];
  const used = [];
  for (let i = list.length - 1; i >= 0 && used.length < max; i--) {
    const h = Number(list[i]?.heading);
    if (Number.isFinite(h)) used.push(h);
  }
  if (!used.length) return Number.isFinite(Number(fallback)) ? Number(fallback) : 0;
  let x = 0;
  let y = 0;
  for (const h of used) {
    const r = (h * Math.PI) / 180;
    x += Math.sin(r);
    y += Math.cos(r);
  }
  return (Math.atan2(x / used.length, y / used.length) * 180) / Math.PI;
}

/** Avancement 0–1 sur la jambe (distance déjà parcourue / portée). */
export function filmLegProgress(leg, lat, lon) {
  const span = filmLegSpanNm(leg);
  if (!(span > 0.01) || !Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return 0;
  const aLat = Number(leg.fromLat);
  const aLon = Number(leg.fromLon);
  const done = haversineNm(aLat, aLon, Number(lat), Number(lon));
  return Math.max(0, Math.min(1, done / span));
}

/**
 * Zoom de jambe : un peu plus large au départ, resserré sur les 10 % d'approche.
 * Les transitions sont petites : l'appelant les applique lentement.
 */
export function filmApproachZoom(baseZoom, progress, { min = FILM_ZOOM_MIN, max = FILM_ZOOM_MAX } = {}) {
  const z = Number(baseZoom);
  const p = Math.max(0, Math.min(1, Number(progress) || 0));
  if (!Number.isFinite(z)) return Math.max(min, Math.min(max, 5));
  let next = z;
  if (p < 0.12) {
    next = z - 0.35 * (1 - p / 0.12);
  } else if (p > 0.9) {
    next = z + 0.4 * ((p - 0.9) / 0.1);
  }
  return Math.max(min, Math.min(max, next));
}

/** Bateau encore à quai : moins que ça entre deux poses = pas bougé. */
export const FILM_CHAPTER_STILL_NM = 0.5;
/** Après un flip de chapitre : pas de panBy / setView pendant ce délai. */
export const FILM_FLIP_HOLD_MS = 1000;
/** Un saut bateau plus grand que ça (transat) = un recadrage, pas une ancre. */
export const FILM_FLIP_NM = 500;

/** Un pas de zoom lent (~0,08 niveau par frame de commit). */
export function stepFilmZoom(from, to, { maxStep = 0.08 } = {}) {
  const a = Number(from);
  const b = Number(to);
  if (!Number.isFinite(b)) return a;
  if (!Number.isFinite(a)) return b;
  const d = b - a;
  if (Math.abs(d) <= maxStep) return b;
  return a + Math.sign(d) * maxStep;
}

/** Centre carte pour placer le bateau au tiers avant (2/3 d'écran devant le cap). */
export function filmViewCenter(lat, lon, headingDeg, map) {
  const heading = Number(headingDeg);
  const h = Number.isFinite(heading) ? heading : 0;
  const rad = (h * Math.PI) / 180;
  if (!map || typeof map.getBounds !== "function") return [lat, lon];
  try {
    const b = map.getBounds();
    const latSpan = b.getNorth() - b.getSouth();
    const lngSpan = b.getEast() - b.getWest();
    if (!Number.isFinite(latSpan) || !Number.isFinite(lngSpan)) return [lat, lon];
    return [
      lat + Math.cos(rad) * latSpan / 6,
      lon + Math.sin(rad) * lngSpan / 6,
    ];
  } catch {
    return [lat, lon];
  }
}

export function lerpHeading(a, b, t) {
  const x = Number(a);
  const y = Number(b);
  if (!Number.isFinite(x)) return Number.isFinite(y) ? y : 0;
  if (!Number.isFinite(y)) return x;
  let d = y - x;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return x + d * t;
}

export function lerpFilmSample(a, b, u) {
  const t = Math.max(0, Math.min(1, Number(u) || 0));
  if (!a) return b || null;
  if (!b) return a;
  const lon0 = Number(a.lon);
  const filmA = Number(a.filmNm);
  const filmB = Number(b.filmNm);
  return {
    lat: Number(a.lat) + (Number(b.lat) - Number(a.lat)) * t,
    lon: lerpLon(lon0, Number(b.lon), t),
    heading: lerpHeading(a.heading, b.heading, t),
    chapterIdx: t < 1 ? a.chapterIdx : b.chapterIdx,
    filmNm: Number.isFinite(filmA) && Number.isFinite(filmB) ? filmA + (filmB - filmA) * t : (Number.isFinite(filmB) ? filmB : filmA),
    t: (Number(a.t) || 0) + ((Number(b.t) || 0) - (Number(a.t) || 0)) * t,
  };
}

/** Échantillons horodatés (horloge murale). On n'en garde que les derniers. */
export function pushFilmSample(samples, sample, { max = 8 } = {}) {
  const list = samples || [];
  if (!sample || !Number.isFinite(Number(sample.lat)) || !Number.isFinite(Number(sample.lon))) {
    return list;
  }
  const next = {
    t: Number(sample.t),
    lat: Number(sample.lat),
    lon: Number(sample.lon),
    heading: Number.isFinite(Number(sample.heading)) ? Number(sample.heading) : 0,
    chapterIdx: Number.isFinite(Number(sample.chapterIdx)) ? Number(sample.chapterIdx) : 0,
    filmNm: Number(sample.filmNm),
  };
  if (!Number.isFinite(next.t)) return list;
  const last = list[list.length - 1];
  if (last && last.t === next.t && last.lat === next.lat && last.lon === next.lon) return list;
  list.push(next);
  if (list.length > max) list.splice(0, list.length - max);
  return list;
}

/** Pose entre deux échantillons : le bateau glisse même si React n'a pas rendu. */
export function interpolateFilmSamples(samples, now) {
  if (!samples?.length) return null;
  const t = Number(now);
  if (!Number.isFinite(t)) return { ...samples[samples.length - 1] };
  if (samples.length === 1 || t <= samples[0].t) return { ...samples[0] };
  const last = samples[samples.length - 1];
  if (t >= last.t) return { ...last };
  let i = 0;
  while (i < samples.length - 1 && samples[i + 1].t < t) i += 1;
  const a = samples[i];
  const b = samples[i + 1];
  if (!b) return { ...a };
  const span = b.t - a.t;
  const u = span > 0 ? (t - a.t) / span : 1;
  const ca = Number(a.chapterIdx);
  const cb = Number(b.chapterIdx);
  if (Number.isFinite(ca) && Number.isFinite(cb) && ca !== cb) {
    return u < 1 ? { ...a } : { ...b };
  }
  const jumpNm = haversineNm(Number(a.lat), Number(a.lon), Number(b.lat), Number(b.lon));
  if (Number.isFinite(jumpNm) && jumpNm > FILM_FLIP_NM) {
    return u < 1 ? { ...a } : { ...b };
  }
  return lerpFilmSample(a, b, u);
}

export function lonLatToTile(lon, lat, z) {
  const zoom = Math.round(Number(z));
  const n = 2 ** zoom;
  const x = Math.floor(((Number(lon) + 180) / 360) * n);
  const latRad = (Number(lat) * Math.PI) / 180;
  const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
  return { x, y, z: zoom };
}

/** Tuiles le long de la jambe au zoom du chapitre (plus les voisines). */
export function tilesAlongLeg(leg, zoom, { pad = 1, samples = 24 } = {}) {
  const aLat = Number(leg?.fromLat);
  const aLon = Number(leg?.fromLon);
  const bLat = Number(leg?.toLat);
  const bLon = Number(leg?.toLon);
  const z = Math.round(Number(zoom));
  if (![aLat, aLon, bLat, bLon, z].every(Number.isFinite) || z < 0) return [];
  const lon1 = unwrapLon(aLon, bLon);
  const out = new Map();
  const n = Math.max(2, Number(samples) || 24);
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const lat = aLat + (bLat - aLat) * u;
    const lon = aLon + (lon1 - aLon) * u;
    const tile = lonLatToTile(lon, lat, z);
    for (let dy = -pad; dy <= pad; dy++) {
      for (let dx = -pad; dx <= pad; dx++) {
        const x = tile.x + dx;
        const y = tile.y + dy;
        const key = `${z}/${x}/${y}`;
        if (!out.has(key)) out.set(key, { z, x, y });
      }
    }
  }
  return [...out.values()];
}

export function filmTileUrl(template, tile) {
  if (!template || !tile) return "";
  return String(template)
    .replace(/\{z\}/g, String(tile.z))
    .replace(/\{y\}/g, String(tile.y))
    .replace(/\{x\}/g, String(tile.x));
}

export function preloadFilmTiles(template, tiles, { ImageCtor = globalThis.Image } = {}) {
  if (!template || !ImageCtor) return [];
  const imgs = [];
  for (const tile of tiles || []) {
    const url = filmTileUrl(template, tile);
    if (!url) continue;
    const img = new ImageCtor();
    if ("decoding" in img) img.decoding = "async";
    img.src = url;
    imgs.push(img);
  }
  return imgs;
}

/** 1 si les tuiles visibles sont là ; 0 si le fond est encore un damier. */
export function filmTilesReady(map, layer) {
  if (!layer) return true;
  try {
    const hasIsLoading = typeof layer.isLoading === "function";
    const tiles = layer._tiles;
    if (!hasIsLoading && (tiles == null || typeof tiles !== "object")) return true;
    if (hasIsLoading && layer.isLoading()) return false;
    if (!tiles) return false;
    const vals = Object.values(tiles);
    if (!vals.length) return false;
    let loaded = 0;
    for (const t of vals) {
      if (t?.loaded || t?.el?.complete) loaded += 1;
    }
    return loaded / vals.length >= FILM_TILE_READY_MIN;
  } catch {
    return true;
  }
}

export function filmPanMaxFrac(tilesReady = true, { boatPx = 0, sizeX = 1280 } = {}) {
  const ready = tilesReady ? 1 : FILM_TILE_SLOW;
  const width = Math.max(1, Number(sizeX) || 1280);
  const speedFrac = Math.max(0, Number(boatPx) || 0) / width;
  const needed = Math.max(FILM_PAN_MAX_SCREEN, speedFrac * 1.35);
  const hard = FILM_SCREEN_STEP_MAX_PX / width;
  return Math.min(FILM_BOAT_KEEP_FRAC, needed, hard) * ready;
}

function currentMapZoom(map, fallback) {
  const z = typeof map?.getZoom === "function" ? Number(map.getZoom()) : NaN;
  return Number.isFinite(z) ? z : fallback;
}

function lastBoatPair(lastBoat) {
  if (!lastBoat) return null;
  if (Array.isArray(lastBoat)) return toLatLngPair(lastBoat);
  return toLatLngPair(lastBoat);
}

/**
 * Translation du plan (CSS / `_rawPanBy`) sans `_resetView`.
 * Repli : `panBy` sans animation, puis `setView` si la carte ne sait pas panner.
 */
export function filmTranslateBy(map, from, to) {
  const a = toLatLngPair(from);
  const b = toLatLngPair(to);
  if (!a || !b) return "hold";
  if (typeof map?.latLngToContainerPoint === "function") {
    const p0 = map.latLngToContainerPoint(a);
    const p1 = map.latLngToContainerPoint(b);
    let dx = (p1.x ?? 0) - (p0.x ?? 0);
    let dy = (p1.y ?? 0) - (p0.y ?? 0);
    const dist = Math.hypot(dx, dy);
    if (dist < 0.05) return "hold";
    if (dist > FILM_SCREEN_STEP_MAX_PX) {
      const s = FILM_SCREEN_STEP_MAX_PX / dist;
      dx *= s;
      dy *= s;
    }
    if (typeof map._rawPanBy === "function") {
      map._rawPanBy({ x: dx, y: dy });
      return "panBy";
    }
    if (typeof map.panBy === "function") {
      map.panBy([dx, dy], { animate: false });
      return "panBy";
    }
  }
  return null;
}

function stillNmFromAnchor(anchor, lat, lon) {
  const a = lastBoatPair(anchor);
  if (!a) return Infinity;
  return haversineNm(a[0], a[1], lat, lon);
}

/**
 * Caméra du film : premier calage et
 * changement d'étape = un `setView` sur le bateau (pas le milieu de jambe) ;
 * ensuite translation du plan. Au changement d'étape, si le bateau n'a pas
 * bougé (Δnm≤0,5), un hold au zoom courant. Sinon un seul `setView`,
 * bateau au centre, puis `FILM_FLIP_HOLD_MS` sans panBy / setView —
 * `FILM_RESET_EVERY` ne produit pas de (0,0) dans cette seconde. En pleine
 * jambe, la caméra suit le bateau par translation (aussi Caraïbes, RC51) ;
 * une ancre (bouée, île, événement) déplace le bateau, pas le centre, sauf
 * sortie d'écran. Hors flip / zoom, le pas écran est borné à 30 px :
 * `keepBoatInFrame` ne peut plus ajouter 54 px après le clamp. `stillAnchor`
 * ne tient que le quai (Δnm≤0,5). Le zoom visé s'approche par `stepFilmZoom`.
 * Pas de `flyTo`.
 */
export function applyFilmCamera(map, {
  chapterIdx,
  lastChapterIdx,
  lat,
  lon,
  heading: _heading,
  zoom,
  now = Date.now(),
  lastSetViewAt = 0,
  flyingUntil = 0,
  lastCenter = null,
  maxFrac,
  framesSinceReset = 0,
  idle = false,
  boatPx = 0,
  lastBoat = null,
  stillAnchor = null,
  filmLeg = null,
} = {}) {
  const desiredBoat = [lat, lon];
  const size = mapSize(map);
  const frac = Number.isFinite(Number(maxFrac))
    ? Number(maxFrac)
    : filmPanMaxFrac(true, { boatPx, sizeX: size.x });
  const mapZoom = currentMapZoom(map, zoom);
  const appliedZoom = stepFilmZoom(mapZoom, zoom);

  if (lastChapterIdx == null) {
    map.setView(desiredBoat, zoom, { animate: false });
    return {
      lastChapterIdx: chapterIdx,
      lastSetViewAt: now,
      flyingUntil: 0,
      action: "setView",
      lastCenter: desiredBoat,
      framesSinceReset: 0,
      stillAnchor: desiredBoat,
    };
  }

  if (chapterIdx !== lastChapterIdx) {
    const from = lastCenter || (typeof map.getCenter === "function"
      ? [map.getCenter().lat, map.getCenter().lng]
      : desiredBoat);
    const prevBoat = lastBoatPair(lastBoat);
    const dNm = prevBoat
      ? haversineNm(prevBoat[0], prevBoat[1], lat, lon)
      : Infinity;
    const still = Number.isFinite(dNm) && dNm <= FILM_CHAPTER_STILL_NM;
    if (still) {
      const target = from || desiredBoat;
      return {
        lastChapterIdx: chapterIdx,
        lastSetViewAt,
        flyingUntil: 0,
        action: "hold",
        lastCenter: target,
        framesSinceReset: 0,
        stillAnchor: desiredBoat,
      };
    }
    map.setView(desiredBoat, appliedZoom, { animate: false });
    return {
      lastChapterIdx: chapterIdx,
      lastSetViewAt: now,
      flyingUntil: now + FILM_FLIP_HOLD_MS,
      action: "setView",
      lastCenter: desiredBoat,
      framesSinceReset: 0,
      stillAnchor: desiredBoat,
    };
  }

  if (Number.isFinite(Number(flyingUntil)) && now < flyingUntil) {
    return {
      lastChapterIdx,
      lastSetViewAt,
      flyingUntil,
      action: "hold",
      lastCenter: lastCenter || desiredBoat,
      framesSinceReset: 0,
      stillAnchor: lastBoatPair(stillAnchor) || desiredBoat,
    };
  }

  const prevHere = lastBoatPair(lastBoat);
  if (prevHere) {
    const jumpNm = haversineNm(prevHere[0], prevHere[1], lat, lon);
    if (Number.isFinite(jumpNm) && jumpNm > FILM_FLIP_NM) {
      map.setView(desiredBoat, appliedZoom, { animate: false });
      return {
        lastChapterIdx,
        lastSetViewAt: now,
        flyingUntil: now + FILM_FLIP_HOLD_MS,
        action: "setView",
        lastCenter: desiredBoat,
        framesSinceReset: 0,
        stillAnchor: desiredBoat,
      };
    }
  }

  const dAnchor = stillNmFromAnchor(stillAnchor, lat, lon);
  const stayOnBoat = Number.isFinite(dAnchor) && dAnchor <= FILM_CHAPTER_STILL_NM;
  const nextAnchor = stayOnBoat ? (lastBoatPair(stillAnchor) || desiredBoat) : null;

  const visual = (typeof map.getCenter === "function"
    ? [map.getCenter().lat, map.getCenter().lng]
    : null);
  const from = lastCenter || (visual && Number.isFinite(visual[0]) ? visual : desiredBoat);
  const rawCenter = stayOnBoat
    ? desiredBoat
    : filmIntraChapterCenter(map, {
      from,
      boat: desiredBoat,
      lastBoat,
      filmLeg,
      maxFrac: frac,
      boatPx,
    });
  const clamped = clampFilmScreenStep(map, from, rawCenter, FILM_SCREEN_STEP_MAX_PX);

  const zoomChanged = Number.isFinite(Number(appliedZoom))
    && Number.isFinite(Number(mapZoom))
    && Math.abs(Number(appliedZoom) - Number(mapZoom)) > 0.04;
  const mustReset = (idle && framesSinceReset > 0) || zoomChanged || framesSinceReset >= FILM_RESET_EVERY;

  if (mustReset) {
    const origin = (visual && Number.isFinite(visual[0])) ? visual : from;
    const resetTo = clampFilmScreenStep(map, origin, clamped, FILM_SCREEN_STEP_MAX_PX);
    map.setView(resetTo, appliedZoom, { animate: false });
    return {
      lastChapterIdx,
      lastSetViewAt: now,
      flyingUntil: 0,
      action: "setView",
      lastCenter: resetTo,
      framesSinceReset: 0,
      stillAnchor: nextAnchor,
    };
  }

  const moved = filmTranslateBy(map, from, clamped);
  if (moved === "panBy") {
    return {
      lastChapterIdx,
      lastSetViewAt,
      flyingUntil: 0,
      action: "panBy",
      lastCenter: clamped,
      framesSinceReset: framesSinceReset + 1,
      stillAnchor: nextAnchor,
    };
  }
  if (moved === "hold") {
    return {
      lastChapterIdx,
      lastSetViewAt,
      flyingUntil,
      action: "hold",
      lastCenter: from,
      framesSinceReset: framesSinceReset + 1,
      stillAnchor: nextAnchor,
    };
  }
  map.setView(clamped, appliedZoom, { animate: false });
  return {
    lastChapterIdx,
    lastSetViewAt: now,
    flyingUntil: 0,
    action: "setView",
    lastCenter: clamped,
    framesSinceReset: 0,
    stillAnchor: nextAnchor,
  };
}

/**
 * Un pas de la boucle impérative : interpole la pose, puis applique la caméra.
 * Cadence dégradée des échantillons → pas toujours ≤ 2 % d'écran (pas de saut).
 */
export function stepFilmCamera(map, {
  samples,
  now,
  lastChapterIdx,
  lastSetViewAt = 0,
  flyingUntil = 0,
  lastCenter = null,
  zoom,
  baseZoom,
  tilesReady = true,
  chapterIdx: chapterOverride,
  filmLeg = null,
  lastBoat = null,
  framesSinceReset = 0,
  stillAnchor = null,
} = {}) {
  let pose = interpolateFilmSamples(samples, Number(now) - FILM_INTERP_DELAY_MS);
  if (!pose || !Number.isFinite(pose.lat) || !Number.isFinite(pose.lon)) {
    return {
      lastChapterIdx,
      lastSetViewAt,
      flyingUntil,
      lastCenter,
      action: "idle",
      pose: null,
      framesSinceReset,
    };
  }
  const chapterIdx = Number.isFinite(Number(chapterOverride)) ? Number(chapterOverride) : pose.chapterIdx;
  if (lastChapterIdx != null && chapterIdx !== lastChapterIdx && samples?.length) {
    for (let i = samples.length - 1; i >= 0; i--) {
      if (Number(samples[i].chapterIdx) === chapterIdx) {
        pose = { ...samples[i] };
        break;
      }
    }
  }
  const heading = smoothFilmHeading(samples, pose.heading);
  const progress = filmLeg ? filmLegProgress(filmLeg, pose.lat, pose.lon) : 0;
  const cruise = Number.isFinite(Number(baseZoom)) ? Number(baseZoom) : zoom;
  const targetZoom = filmLeg && !filmLegIsArchipelago(filmLeg)
    ? filmApproachZoom(cruise, progress)
    : cruise;
  const appliedZoom = stepFilmZoom(zoom, targetZoom);
  const prevBoat = lastBoatPair(lastBoat);
  const chapterFlip = lastChapterIdx != null && chapterIdx !== lastChapterIdx;
  let jumpNm = 0;
  if (prevBoat) {
    jumpNm = haversineNm(prevBoat[0], prevBoat[1], pose.lat, pose.lon);
  }
  const teleport = chapterFlip || (Number.isFinite(jumpNm) && jumpNm > FILM_FLIP_NM);
  if (prevBoat && !teleport) {
    const limited = clampFilmScreenStep(map, prevBoat, [pose.lat, pose.lon], FILM_SCREEN_STEP_MAX_PX);
    if (limited) {
      pose = { ...pose, lat: limited[0], lon: limited[1] };
    }
  }
  let boatPx = 0;
  if (prevBoat && typeof map?.latLngToContainerPoint === "function") {
    const a = map.latLngToContainerPoint(prevBoat);
    const b = map.latLngToContainerPoint([pose.lat, pose.lon]);
    boatPx = Math.hypot((b.x ?? 0) - (a.x ?? 0), (b.y ?? 0) - (a.y ?? 0));
  }
  const idle = Boolean(lastBoat) && boatPx < 0.4;
  const size = mapSize(map);
  const next = applyFilmCamera(map, {
    chapterIdx,
    lastChapterIdx,
    lat: pose.lat,
    lon: pose.lon,
    heading,
    zoom: appliedZoom,
    now,
    lastSetViewAt,
    flyingUntil,
    lastCenter,
    maxFrac: filmPanMaxFrac(tilesReady, { boatPx, sizeX: size.x }),
    framesSinceReset,
    idle,
    boatPx,
    lastBoat,
    stillAnchor,
    filmLeg,
  });
  return { ...next, pose: { ...pose, heading }, boatPx, zoom: appliedZoom };
}
