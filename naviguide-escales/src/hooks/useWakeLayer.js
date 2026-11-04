import { useEffect, useRef } from "react";
import L from "leaflet";
import { wakeCursorAt } from "../engine/filmWake.js";
import { WAKE_DONE_COLOR, WAKE_REST_COLOR } from "../layers/styles.js";
import { unwrapLon } from "../utils/geo.js";

const WORLD_OFFSETS = [0, 360, -360];

const WAKE_STYLE = {
  color: WAKE_DONE_COLOR,
  weight: 4,
  opacity: 0.92,
  pane: "route",
  interactive: false,
};

const REST_STYLE = {
  color: WAKE_REST_COLOR,
  weight: 4,
  opacity: 0.88,
  pane: "route",
  interactive: false,
};

function latLngs(coords, worldOffset = 0) {
  return coords.map(([lon, lat]) => [lat, lon + worldOffset]);
}

function isSidePointIndex(episodes, index) {
  return (episodes || []).some((ep) => index > ep.ja && index < ep.jb);
}

function staticWakeParts(flat) {
  const points = flat?.points || [];
  const episodes = flat?.episodes || [];
  const parts = [];
  const partByPoint = new Array(points.length);
  const linePointByIndex = new Array(points.length);
  let current = null;

  points.forEach((point, index) => {
    if (!Number.isFinite(point?.lon) || !Number.isFinite(point?.lat)) return;
    if (isSidePointIndex(episodes, index)) {
      current = null;
      return;
    }
    if (!current || point.jump) {
      current = [];
      parts.push(current);
    }
    const lon = current.length ? unwrapLon(current.at(-1)[0], point.lon) : point.lon;
    const linePoint = [lon, point.lat];
    current.push(linePoint);
    partByPoint[index] = parts.length - 1;
    linePointByIndex[index] = linePoint;
  });

  return { points, parts, partByPoint, linePointByIndex };
}

function createWorldLines(group, style) {
  return WORLD_OFFSETS.map(() => L.polyline([], style).addTo(group));
}

function setTail(lines, from, to) {
  if (!from || !to) {
    lines.forEach((line) => line.setLatLngs([]));
    return;
  }
  const coords = [[from.lon, from.lat], [to.lon, to.lat]];
  lines.forEach((line, index) => {
    line.setLatLngs(latLngs(coords, WORLD_OFFSETS[index]));
  });
}

function clearDoneLines(lines) {
  lines.forEach((worldLines) => {
    worldLines.forEach((line) => line.setLatLngs([]));
  });
}

function appendDonePoint(geometry, index) {
  const point = geometry.linePointByIndex[index];
  const partIndex = geometry.partByPoint[index];
  if (!point || partIndex == null) return;
  geometry.doneLines[partIndex].forEach((line, worldIndex) => {
    line.addLatLng([point[1], point[0] + WORLD_OFFSETS[worldIndex]]);
  });
}

function syncWake(geometry, sailNm) {
  const target = Math.max(0, Number(sailNm) || 0);
  const targetIndex = wakeCursorAt(
    { points: geometry.points },
    target,
    geometry.completedIndex,
  );
  if (targetIndex < geometry.completedIndex) {
    clearDoneLines(geometry.doneLines);
    geometry.completedIndex = -1;
  }
  while (geometry.completedIndex < targetIndex) {
    geometry.completedIndex += 1;
    appendDonePoint(geometry, geometry.completedIndex);
  }

  const previous = geometry.points[geometry.completedIndex];
  const next = geometry.points[geometry.completedIndex + 1];
  const samePart = previous && next
    && geometry.partByPoint[geometry.completedIndex] === geometry.partByPoint[geometry.completedIndex + 1];
  if (!previous || !next || next.jump || !samePart) {
    setTail(geometry.tailLines, null, null);
    return;
  }
  const span = (next.cumNm ?? 0) - (previous.cumNm ?? 0);
  const ratio = span > 0
    ? Math.max(0, Math.min(1, (target - (previous.cumNm ?? 0)) / span))
    : 0;
  const nextLon = unwrapLon(previous.lon, next.lon);
  setTail(geometry.tailLines, previous, {
    lon: previous.lon + ratio * (nextLon - previous.lon),
    lat: previous.lat + ratio * (next.lat - previous.lat),
  });
}

/**
 * Accompli = bleu clair. Reste = bleu foncé. Leaflet only — no deck.gl.
 */
export function useWakeLayer(mapRef, { flat, sailNm, enabled, mapReady }) {
  const groupRef = useRef(null);
  const geometryRef = useRef(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !enabled) {
      groupRef.current?.remove();
      groupRef.current = null;
      geometryRef.current = null;
      return undefined;
    }
    const group = L.layerGroup().addTo(map);
    const geometry = staticWakeParts(flat);
    geometry.parts.forEach((part) => {
      if (part.length < 2) return;
      WORLD_OFFSETS.forEach((worldOffset) => {
        L.polyline(latLngs(part, worldOffset), REST_STYLE).addTo(group);
      });
    });
    geometry.doneLines = geometry.parts.map(() => createWorldLines(group, WAKE_STYLE));
    geometry.tailLines = createWorldLines(group, WAKE_STYLE);
    geometry.completedIndex = -1;
    groupRef.current = group;
    geometryRef.current = geometry;
    return () => {
      group.remove();
      groupRef.current = null;
      geometryRef.current = null;
    };
  }, [mapRef, mapReady, enabled, flat]);

  useEffect(() => {
    const geometry = geometryRef.current;
    if (!geometry || !enabled) return;
    syncWake(geometry, sailNm);
  }, [sailNm, enabled]);
}
