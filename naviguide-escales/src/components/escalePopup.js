import { VIEW_SUIVRE, VIEW_TRACER } from "../constants/viewMode.js";
import { deltaLon, haversineNm } from "../utils/geo.js";

export const ESCALE_POPUP_MAX_WIDTH = 340;
export const ESCALE_POPUP_MAX_HEIGHT = 260;

const ESCALE_CLOSE_SEL = "[data-testid='escale-close']";

/** Changement de vue, Revoir, ou film en cours : la fiche d'escale disparaît
 * (RA5 + DM7 : Suivre → Tracer ne doit pas garder la fiche de Papeete). */

export function shouldCloseEscaleSheet({
  nextView,
  replayActive = false,
  replayStarting = false,
} = {}) {
  if (replayActive || replayStarting) return true;
  return nextView === VIEW_SUIVRE || nextView === VIEW_TRACER;
}

export function isEscaleCloseClick(event) {
  return Boolean(event?.target?.closest?.(ESCALE_CLOSE_SEL));
}

/** Ferme l'état React ; ignore le clic drapeau qui suivrait le retrait du popup. */
export function requestEscaleClose(sheet) {
  globalThis.__naviguideIgnoreEscaleOpen = Date.now() + 400;
  sheet?.onClose?.();
  return true;
}

/** Hors dessin : ouvre la fiche. En dessin : le clic reste au mode tracer. */
export function handleWaypointMarkerClick(drawing, point, index, callbacks) {
  if (drawing) {
    callbacks?.onDrawingWaypointClick?.(point, index);
    return "draw";
  }
  const ignoreUntil = Number(globalThis.__naviguideIgnoreEscaleOpen);
  if (Number.isFinite(ignoreUntil) && ignoreUntil > Date.now()) {
    return "ignore";
  }
  callbacks?.onWaypointClick?.(point, index);
  return "sheet";
}

export function createEscalePopupOptions() {
  return {
    autoPan: true,
    closeButton: false,
    className: "escale-popup",
    maxWidth: ESCALE_POPUP_MAX_WIDTH,
    minWidth: 220,
    closeOnClick: false,
    autoClose: false,
    keepInView: false,
  };
}

export function ensureEscalePopup(popup, L) {
  return popup || L.popup(createEscalePopupOptions());
}

function sameStop(point, stop) {
  if (!point || !stop) return false;
  if (stop.name && point.name && stop.name === point.name) return true;
  if (!Number.isFinite(stop.lat) || !Number.isFinite(point.lat)) return false;
  if (Math.abs(point.lat - stop.lat) > 1e-4) return false;
  const a = Number(point.lon);
  const b = Number(stop.lon);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return Math.abs(deltaLon(b, a)) < 1e-3;
}

function closestToCamera(scene, matches) {
  if (!matches.length) return null;
  const cam = scene.map?.getCenter?.()?.lng;
  if (!Number.isFinite(cam)) return matches[0];
  return matches.reduce((best, marker) => {
    const lng = marker.getLatLng?.()?.lng;
    const bl = best.getLatLng?.()?.lng;
    if (!Number.isFinite(lng)) return best;
    if (!Number.isFinite(bl)) return marker;
    return Math.abs(lng - cam) < Math.abs(bl - cam) ? marker : best;
  });
}

function markerMatchesStop(marker, stop, maxNm = 5) {
  if (!marker || !stop) return false;
  const point = marker._naviguideWaypoint;
  if (point && sameStop(point, stop)) return true;
  const ll = marker.getLatLng?.();
  if (!ll || !Number.isFinite(stop.lat) || !Number.isFinite(ll.lat)) return false;
  const lon = Number.isFinite(Number(stop.lon)) ? Number(stop.lon) : Number(stop.lng);
  if (!Number.isFinite(lon) || !Number.isFinite(ll.lng)) return false;
  return haversineNm(stop.lat, lon, ll.lat, ll.lng) <= maxNm;
}

/** Catamaran live parqué (Cayenne pendant l'épisode) — ancre de la fiche. */
export function findParkedBoatMarker(scene, stop) {
  const markers = scene?.markerSets?.get?.("live");
  if (!markers || !stop) return null;
  const matches = [];
  for (const marker of markers) {
    if (markerMatchesStop(marker, stop)) matches.push(marker);
  }
  return closestToCamera(scene, matches);
}

/** Copie monde du drapeau la plus proche du centre carte ; sinon le bateau parqué. */
export function findWaypointMarker(scene, stop) {
  const markers = scene?.waypointMarkers;
  const matches = [];
  if (markers && stop) {
    for (const marker of markers.values()) {
      if (sameStop(marker._naviguideWaypoint, stop)) matches.push(marker);
    }
  }
  const flag = closestToCamera(scene, matches);
  const boat = findParkedBoatMarker(scene, stop);
  return boat || flag;
}
