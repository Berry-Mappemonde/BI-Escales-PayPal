import {
  computeMarkerOffsets,
  capOffset,
  FLAG_GAP,
  FLAG_H,
  FLAG_W,
  hasFlag,
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

const BOAT_ICON = 64;
const BOAT_ANCHOR = [32, 32];
const BOAT_PAD = 4;

function rectsOverlap(a, b, pad = FLAG_GAP) {
  return (
    a.x < b.x + b.w + pad &&
    a.x + a.w + pad > b.x &&
    a.y < b.y + b.h + pad &&
    a.y + a.h + pad > b.y
  );
}

export function stopFlagScreenRect(origin, offset) {
  const [ox, oy] = offset || [0, 0];
  return {
    x: origin.x + ox - FLAG_W / 2,
    y: origin.y + oy - FLAG_H,
    w: FLAG_W,
    h: FLAG_H,
  };
}

export function boatScreenRect(origin, offset) {
  const anchor = offsetToIconAnchor(BOAT_ANCHOR, offset);
  return {
    x: origin.x - anchor[0],
    y: origin.y - anchor[1],
    w: BOAT_ICON,
    h: BOAT_ICON,
  };
}

/** Screen sample points inside a rect (for hit-target overlap probes). */
export function rectSamplePoints(rect, steps = 7) {
  const pts = [];
  for (let iy = 0; iy < steps; iy++) {
    for (let ix = 0; ix < steps; ix++) {
      pts.push({
        x: rect.x + (rect.w * ix) / (steps - 1),
        y: rect.y + (rect.h * iy) / (steps - 1),
      });
    }
  }
  return pts;
}

export function boatOverlapsStopFlag(boatOffset, boatOrigin, stopOrigin, stopOffset, pad = BOAT_PAD) {
  const boat = boatScreenRect(boatOrigin, boatOffset);
  const flag = stopFlagScreenRect(stopOrigin, stopOffset);
  return rectsOverlap(boat, flag, pad);
}

const BOAT_DIRS = [
  [0, -1],
  [0.7, -1],
  [-0.7, -1],
  [1, -0.7],
  [-1, -0.7],
  [1, 0],
  [-1, 0],
  [1, 0.7],
  [-1, 0.7],
  [0.7, 1],
  [-0.7, 1],
  [0, 1],
];

const BOAT_RADII = [40, 56, 72, 88, 104];

/**
 * Place the catamaran icon so its 64×64 hit box never covers a stop flag at the current zoom.
 */
export function boatMarkerAnchorOffset(boat, stops, stopOffsets, project) {
  if (!boat || !Number.isFinite(boat.lat) || !Number.isFinite(boat.lon) || typeof project !== "function") {
    return [0, 0];
  }
  const origin = project(boat.lon, boat.lat);
  const flagRects = [];
  for (let i = 0; i < (stops || []).length; i++) {
    const stop = stops[i];
    if (!hasFlag(stop)) continue;
    const o = project(stop.lon, stop.lat);
    flagRects.push(stopFlagScreenRect(o, stopOffsets[i]));
  }
  if (!flagRects.length) return [0, 0];

  let best = [72, -72];
  let bestScore = Infinity;

  for (const radius of BOAT_RADII) {
    for (const [dx, dy] of BOAT_DIRS) {
      const candidate = capOffset(dx * radius, dy * radius, 104);
      const boatRect = boatScreenRect(origin, candidate);
      let overlapPenalty = 0;
      for (const flag of flagRects) {
        if (rectsOverlap(boatRect, flag, BOAT_PAD)) overlapPenalty += 5000;
      }
      const score = Math.hypot(candidate[0], candidate[1]) + overlapPenalty;
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    }
    if (bestScore < 500) break;
  }

  return best;
}

export { offsetToIconAnchor };
