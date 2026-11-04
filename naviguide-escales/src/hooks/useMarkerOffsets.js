import { useState, useEffect, useCallback, useRef } from "react";
import { computeMarkerOffsets, projectRouteSegments } from "../utils/markerOffsets.js";
import { cameraLngForBoat, markerWorldLngs } from "../utils/waypointFlags.js";

const DEBOUNCE_MS = 120;
export const CAMERA_IDLE_MS = 950;
/** Attendre la fin du zoom avant de recalculer les offsets. */
export const ZOOM_IDLE_MS = 250;

export function markerOffsetDelay(cameraFollowing, reason = "move") {
  if (reason === "zoom") return ZOOM_IDLE_MS;
  return cameraFollowing ? CAMERA_IDLE_MS : DEBOUNCE_MS;
}

/** Aucun recalcul d'offsets pendant l'animation de zoom Leaflet. */
export function shouldComputeOffsetsOnEvent(type) {
  return type !== "zoomanim";
}

/**
 * La vue touche l'antiméridien (±180°) : bornes inversées, étendue hors
 * [−180, 180], ou marge de 10° pour les drapeaux près de la ligne.
 */
export function viewTouchesAntimeridian(west, east) {
  if (!Number.isFinite(west) || !Number.isFinite(east)) return false;
  if (west > east) return true;
  if (west <= -180 || east >= 180) return true;
  return west < -170 || east > 170;
}

/** Copies-monde des drapeaux seulement si la vue touche ±180°. */
export function flagWorldLngsForView(lon, cameraLng, west, east) {
  if (viewTouchesAntimeridian(west, east)) return markerWorldLngs(lon, cameraLng);
  const aligned = cameraLngForBoat(lon, cameraLng);
  return Number.isFinite(aligned) ? [aligned] : [];
}

export function useMarkerOffsets(points, mapRef, routeCoords = [], { cameraFollowing = false } = {}) {
  const [offsets, setOffsets] = useState(() => points.map(() => [0, 0]));
  const timerRef = useRef(null);

  const compute = useCallback(() => {
    const map = mapRef.current;
    if (!map || !points.length) return;
    const project = (lon, lat) => {
      const pt = map.latLngToLayerPoint([lat, lon]);
      return { x: pt.x, y: pt.y };
    };
    const routeSegs = projectRouteSegments(routeCoords, project);
    setOffsets(computeMarkerOffsets(points, project, routeSegs));
  }, [points, mapRef, routeCoords]);

  useEffect(() => {
    if (!points.length) return undefined;
    const schedule = (delay) => {
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(compute, delay);
    };
    const afterCameraStop = () => schedule(markerOffsetDelay(cameraFollowing));
    const afterZoom = () => schedule(ZOOM_IDLE_MS);
    const holdDuringZoom = () => {
      clearTimeout(timerRef.current);
    };
    const attach = () => {
      const map = mapRef.current;
      if (!map) return false;
      map.on("zoomanim", holdDuringZoom);
      map.on("zoomend", afterZoom);
      map.on("moveend", afterCameraStop);
      compute();
      return true;
    };
    if (!attach()) {
      const poll = setInterval(() => {
        if (attach()) clearInterval(poll);
      }, 200);
      return () => {
        clearInterval(poll);
        clearTimeout(timerRef.current);
      };
    }
    return () => {
      clearTimeout(timerRef.current);
      const map = mapRef.current;
      if (map) {
        map.off("zoomanim", holdDuringZoom);
        map.off("zoomend", afterZoom);
        map.off("moveend", afterCameraStop);
      }
    };
  }, [compute, mapRef, points, cameraFollowing]);

  return offsets;
}
