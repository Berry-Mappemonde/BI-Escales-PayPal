import { wrapLon } from "./geo.js";
import { worldCopyLngs } from "./gribSymbols.js";

/** Sources d’image : `flags` (1 ou 2) ou l’ancien champ unique `flag`. */
export function waypointFlagSrcs(point) {
  if (Array.isArray(point?.flags) && point.flags.length) {
    return point.flags.filter(Boolean);
  }
  if (point?.flag) return [point.flag];
  return [];
}

export function flagMarkerHtml(srcs, offset = [0, 0]) {
  const [ox, oy] = offset;
  if (!srcs.length) return "";
  const imgs = srcs
    .map((src) => `<img src="${src}" alt="" style="height:22px;width:auto;display:block" />`)
    .join("");
  return `<div class="flag-stack" style="display:flex;align-items:center;gap:2px;transform:translate(${ox}px,${oy}px)">${imgs}</div>`;
}

export function flagIconMetrics(srcs) {
  const n = Math.max(1, srcs.length);
  const w = 22 * n + 2 * Math.max(0, n - 1) + 4;
  return { iconSize: [w, 24], iconAnchor: [Math.round(w / 2), 12] };
}

/** Rond de tracé : 14 px (remplissage + bordure), ancré au centre du clic. */
export const DRAWING_PIN_PX = 14;

export function drawingPinMetrics() {
  const half = DRAWING_PIN_PX / 2;
  return { iconSize: [DRAWING_PIN_PX, DRAWING_PIN_PX], iconAnchor: [half, half] };
}

export function drawingPinHtml(index, attrs = "") {
  const fill = index === 0 ? "#22c55e" : "#e2e8f0";
  return `<div${attrs} style="width:${DRAWING_PIN_PX}px;height:${DRAWING_PIN_PX}px;box-sizing:border-box;border-radius:50%;background:${fill};border:2px solid #0f172a"></div>`;
}

function uniqLngs(lngs) {
  const out = [];
  for (const lng of lngs) {
    if (!Number.isFinite(lng)) continue;
    if (out.every((x) => Math.abs(x - lng) > 1e-6)) out.push(lng);
  }
  return out;
}

/** Copie monde la plus proche du centre caméra (même wrap que la vue). */
export function lonOnCameraCopy(lon, cameraLng) {
  const x = Number(lon);
  if (!Number.isFinite(x)) return lon;
  const copies = uniqLngs([...worldCopyLngs(x), wrapLon(x)]);
  if (!copies.length) return x;
  if (cameraLng == null || cameraLng === "") return x;
  const cam = Number(cameraLng);
  if (!Number.isFinite(cam)) return x;
  return copies.reduce((best, v) => (Math.abs(v - cam) < Math.abs(best - cam) ? v : best));
}

/**
 * Même lon que le sillage (horloge, éventuellement dépliée) tant qu’on n’a pas
 * de centre carte. Dès qu’il y en a un, on colle à cette copie (après jump).
 */
export function cameraLngForBoat(lon, prevCameraLng) {
  return lonOnCameraCopy(lon, prevCameraLng);
}

/**
 * Bateau / drapeaux : d’abord la lon caméra, puis les copies ±360° comme la route.
 * Sans ça, près de 180°, la carte (unwrap / worldCopyJump) regarde une copie
 * et le marqueur unique reste sur l’autre.
 */
export function markerWorldLngs(lon, cameraLng) {
  const x = Number(lon);
  if (!Number.isFinite(x)) return [];
  const aligned = cameraLngForBoat(x, cameraLng);
  const extras = uniqLngs([
    ...worldCopyLngs(x),
    ...worldCopyLngs(wrapLon(x)),
  ]).filter((lng) => Math.abs(lng - aligned) > 1e-6);
  return [aligned, ...extras];
}

export { worldCopyLngs, wrapLon };
