/**
 * Une seule règle « cadrage Suivre » :
 * centre = position live du bateau, zoom = plancher (monde une fois, pas deux).
 * Tracer / dessin gardent showWorld (centre historique) ; le film garde filmCamera.
 */
import { cameraLngForBoat } from "../utils/waypointFlags.js";
import { shouldPlaceInitialCamera, shouldResnapCamera } from "../utils/sceneGate.js";
import { followMinZoom } from "./zoomFloor.js";

export function followCadrageZoom(size, snap = 0.25, floor = 0) {
  return followMinZoom(size, snap, floor);
}

export function followCadrageCenter(live, prevFollowLon) {
  if (!live || !Number.isFinite(Number(live.lat)) || !Number.isFinite(Number(live.lon))) return null;
  return [Number(live.lat), cameraLngForBoat(live.lon, prevFollowLon)];
}

/**
 * Premier calage dès que le live est connu, et après reset d'entrée Suivre.
 * Jamais contre un geste (userNavigated), jamais pendant le film ou le dessin.
 * Une seule fois pour une même position (shouldResnapCamera).
 */
export function shouldFrameFollowLive({
  isSuivre = false,
  filmActive = false,
  drawingMode = false,
  live = null,
  userNavigated = false,
  initialLive = null,
  pending = false,
} = {}) {
  if (!isSuivre || filmActive || drawingMode) return false;
  if (!pending && !shouldPlaceInitialCamera({ userNavigated })) return false;
  if (!followCadrageCenter(live)) return false;
  if (!pending && initialLive && !shouldResnapCamera(initialLive, live)) return false;
  return true;
}

export function applyFollowCadrage(map, live, {
  followLon = null,
  minZoom = 0,
  move = null,
} = {}) {
  const center = followCadrageCenter(live, followLon);
  if (!map || !center) return null;
  const zoom = followCadrageZoom(map.getSize?.(), map.options?.zoomSnap, minZoom);
  const run = typeof move === "function" ? move : (fn) => fn();
  run(() => map.setView(center, zoom, { animate: false }));
  return { center, zoom, followLon: center[1] };
}
