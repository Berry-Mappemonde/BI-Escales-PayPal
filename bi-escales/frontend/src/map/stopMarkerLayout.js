import {
  computeMarkerOffsets,
  offsetToIconAnchor,
  projectRouteSegments,
} from "../../../../naviguide-escales/src/utils/markerOffsets.js";

export function maritimeRouteCoords(segments) {
  return (segments || []).filter((segment) => !segment.nonMaritime).flatMap((segment) => segment.coords || []);
}

export function computeStopOffsets(stops, segments, project, previous = []) {
  const routeSegs = projectRouteSegments(maritimeRouteCoords(segments), project);
  return computeMarkerOffsets(stops || [], project, routeSegs, previous);
}

/** Keep the catamaran hit target away from a stop sharing the same lat/lng. */
export function boatMarkerAnchorOffset(boat, stops, stopOffsets) {
  if (!boat || !Number.isFinite(boat.lat) || !Number.isFinite(boat.lon)) {
    return [0, 0];
  }
  for (let i = 0; i < (stops || []).length; i++) {
    const stop = stops[i];
    if (Math.abs(stop.lat - boat.lat) < 1e-4 && Math.abs(stop.lon - boat.lon) < 1e-4) {
      const [ox, oy] = stopOffsets[i] || [0, 0];
      return [-(ox || 0) + 36, -(oy || 0) - 8];
    }
  }
  return [0, 0];
}

export { offsetToIconAnchor };
