import { useCallback, useEffect, useRef, useState } from "react";
import { coordsFromRoutePayload } from "../utils/berryLegs.js";
import { haversineNm, unwrapPath, wrapLon } from "../utils/geo.js";
import { ROUTE_IMPORT_MAX_POINTS } from "../utils/routeImport.js";

const API_URL = import.meta.env?.VITE_API_URL ?? "";
export const DRAW_MAX_POINTS = ROUTE_IMPORT_MAX_POINTS;

// Legs are stored by slot (leg i joins point i to point i + 1). What leaves the
// hook is always dense: a leg still loading, or refused, is simply absent.
function denseSegments(segments) {
  return (segments || []).filter(Boolean);
}

function lengthNm(data, coords) {
  const props = data?.properties || {};
  const raw = Number(props.length);
  if (Number.isFinite(raw) && raw >= 0) {
    const units = String(props.units || "km").toLowerCase();
    if (units === "nm" || units === "nmi") return raw;
    if (units === "m") return raw / 1852;
    return raw / 1.852;
  }
  let nm = 0;
  const line = coords || [];
  for (let i = 1; i < line.length; i += 1) {
    nm += haversineNm(line[i - 1][1], line[i - 1][0], line[i][1], line[i][0]);
  }
  return nm;
}

/**
 * One leg from /route. Nothing is ever drawn that the server did not route:
 * on a server error (500, 404, an answer without a line) or a network failure
 * the leg is absent and the point stays, as after a 503 — no straight line,
 * which could cross land.
 */
export async function loadLeg(from, to) {
  const params = new URLSearchParams({
    start_lat: String(from.lat),
    start_lon: String(wrapLon(from.lon)),
    end_lat: String(to.lat),
    end_lon: String(wrapLon(to.lon)),
  });
  try {
    const res = await fetch(`${API_URL}/route?${params}`);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    const detail = typeof data?.detail === "string" ? data.detail : "";
    if (res.status === 422 && detail === "on_land") {
      // The server names the end on land; an older one does not (the end).
      return { reject: "on_land", end: data?.end === "on_land_start" ? "start" : "end" };
    }
    if (res.status === 422 && detail === "crosses_land") return { reject: "crosses_land", end: "end" };
    // Out of time or slots: not land. Say so; the point stays.
    if (res.status === 503) return { busy: true };
    let coords = coordsFromRoutePayload(data);
    if (!res.ok || !coords.length) return { error: "server" };
    coords = unwrapPath(coords, from.lon);
    return { coords, nm: lengthNm(data, coords) };
  } catch {
    return { error: "network" };
  }
}

/**
 * Whether a leg still on the drawing is loading. `pending` maps a leg slot to
 * the number of fetches in flight for it; a slot past the last point (its
 * point was undone) no longer counts, the others keep the spinner on.
 */
export function legsStillLoading(pending, pointCount) {
  const lastSlot = Number(pointCount) - 2;
  for (const [slot, count] of pending || []) {
    if (count > 0 && slot <= lastSlot) return true;
  }
  return false;
}

const REFUSAL_KEYS = {
  on_land: "pointOnLand",
  crosses_land: "rhumbCrossesLand",
};

/** Phrase already used for a 422 land answer. Empty when the leg was routed. */
export function drawingRefusalPhrase(code, translate) {
  const key = REFUSAL_KEYS[code];
  if (!key || typeof translate !== "function") return "";
  return translate(key) || "";
}

/**
 * Terminer stays disabled while a leg is loading, or while a land refusal
 * left the chain short. A complete sea chain (one segment per gap) enables it.
 * A server error that keeps every point, with no land notice, is unchanged.
 */
export function canFinishDrawnRoute(pointCount, segmentCount, loading, notice) {
  if (loading) return false;
  const points = Number(pointCount) || 0;
  const segments = Number(segmentCount) || 0;
  if (notice === "on_land" || notice === "crosses_land") {
    if (points < 2 || segments < points - 1) return false;
  }
  return points >= 2;
}

/** Same path as N map clicks: clear, then one addPoint per imported waypoint. */
export async function importPointsSequential(addPoint, reset, points) {
  reset();
  for (const p of points || []) {
    const lat = Number(p.lat);
    const lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    await addPoint(lat, lon, p.name ? { name: String(p.name) } : undefined);
  }
}

function publishDrawn(points, segments) {
  if (typeof window === "undefined") return;
  const legs = denseSegments(segments);
  window.__naviguideDrawn = {
    points,
    segments: legs,
    coords: legs.flatMap((s) => s.coords || []),
  };
}

/**
 * The drawn route itself (moved out of App.jsx, behaviour unchanged):
 * points and searoute segments, undo / redo, the GeoJSON handed to the plan.
 * App keeps the orchestration around it (entering / leaving the mode, camera,
 * cinema, plan reset) — this hook never touches the scene or the view.
 */
export function useRouteDrawing() {
  const [drawingMode, setDrawingMode] = useState(false);
  const [drawnPoints, setDrawnPoints] = useState([]);
  const [drawnSegments, setDrawnSegments] = useState([]);
  const [drawingLoading, setDrawingLoading] = useState(false);
  const [drawingNotice, setDrawingNotice] = useState(null);
  const [canRedo, setCanRedo] = useState(false);
  const pointsRef = useRef([]);
  const segmentsRef = useRef([]);
  const undonePointsRef = useRef([]);
  const undoneSegmentsRef = useRef([]);
  const epochRef = useRef(0);
  const queueRef = useRef(Promise.resolve());
  const pendingSlotsRef = useRef(new Map());
  // Generation per leg slot: bumped when the leg is undone or replaced, so a
  // late answer for the old leg is dropped. Shifted with the points when one
  // is removed from the middle.
  const slotGenRef = useRef([]);
  const noticeTokenRef = useRef(0);

  // Reset n'est appelé que pour un abandon explicite (Annuler / supprimer).
  // Mettre le brouillon de côté (pilule Berry, Suivre) laisse points et segments.
  const reset = useCallback(() => {
    setDrawnPoints([]);
    setDrawnSegments([]);
    setCanRedo(false);
    pointsRef.current = [];
    segmentsRef.current = [];
    undonePointsRef.current = [];
    undoneSegmentsRef.current = [];
    epochRef.current += 1;
    slotGenRef.current = [];
    pendingSlotsRef.current = new Map();
    setDrawingLoading(false);
    setDrawingNotice(null);
    publishDrawn([], []);
  }, []);

  const notify = useCallback((code) => {
    noticeTokenRef.current += 1;
    setDrawingNotice({ code, token: noticeTokenRef.current });
  }, []);

  // The point appears at once (same as a plain click); legs resolve
  // afterwards, one at a time, in click order.
  const enqueue = useCallback((work) => {
    const job = queueRef.current.then(work);
    queueRef.current = job.then(() => {}, () => {});
    return job;
  }, []);

  // Removes the point at `index` wherever it is, and joins its neighbours
  // with a new leg (fetched like any other).
  const removePointAt = useCallback((index, refetch) => {
    const pts = pointsRef.current;
    if (index < 0 || index >= pts.length) return;
    const before = pts[index - 1] || null;
    const after = pts[index + 1] || null;
    const g = slotGenRef.current;
    slotGenRef.current = index === 0
      ? g.slice(1)
      : [...g.slice(0, index - 1), Math.max(g[index - 1] || 0, g[index] || 0) + 1, ...g.slice(index + 1)];
    const segs = segmentsRef.current;
    const nextSegs = index === 0
      ? segs.slice(1)
      : [...segs.slice(0, index - 1), undefined, ...segs.slice(index + 1)];
    pointsRef.current = [...pts.slice(0, index), ...pts.slice(index + 1)];
    segmentsRef.current = nextSegs.slice(0, Math.max(0, pointsRef.current.length - 1));
    undonePointsRef.current = [];
    undoneSegmentsRef.current = [];
    setCanRedo(false);
    setDrawnPoints([...pointsRef.current]);
    setDrawnSegments(denseSegments(segmentsRef.current));
    publishDrawn(pointsRef.current, segmentsRef.current);
    if (before && after) refetch(before, after);
  }, []);

  const loadSegment = useCallback(async (from, to) => {
    const slot = pointsRef.current.indexOf(from);
    // The leg was undone (or replaced) before its turn came: nothing to fetch.
    if (slot < 0 || pointsRef.current[slot + 1] !== to) return;
    const seen = epochRef.current;
    const gen = slotGenRef.current[slot] || 0;
    const slots = pendingSlotsRef.current;
    slots.set(slot, (slots.get(slot) || 0) + 1);
    setDrawingLoading(true);
    try {
      const result = await loadLeg(from, to);
      if (epochRef.current !== seen) return;
      // Points may have moved (one removed before): find the leg again.
      const at = pointsRef.current.indexOf(from);
      if (at < 0 || pointsRef.current[at + 1] !== to) return;
      // A late answer for a leg that was undone meanwhile is dropped.
      if ((slotGenRef.current[at] || 0) !== gen) return;
      if (result?.busy) {
        notify("busy");
        return;
      }
      // Server error or network failure: the point stays, without a leg.
      if (result?.error) {
        notify(result.error === "network" ? "network_error" : "server_error");
        return;
      }
      if (result?.reject) {
        // Remove the point at fault (on land, or the end of a leg across
        // land) wherever it is, then join its neighbours.
        const bad = result.end === "start" ? from : to;
        const index = pointsRef.current.indexOf(bad);
        if (index >= 0) removePointAt(index, (a, b) => fetchSegmentRef.current(a, b));
        notify(result.reject);
        return;
      }
      const next = segmentsRef.current.slice();
      next[at] = {
        coords: result.coords,
        nm: result.nm,
        from,
        to,
      };
      segmentsRef.current = next.slice(0, Math.max(0, pointsRef.current.length - 1));
      setDrawnSegments(denseSegments(segmentsRef.current));
      publishDrawn(pointsRef.current, segmentsRef.current);
      setDrawingNotice(null);
    } finally {
      const left = (slots.get(slot) || 0) - 1;
      if (left > 0) slots.set(slot, left);
      else slots.delete(slot);
      if (slots === pendingSlotsRef.current) {
        setDrawingLoading(legsStillLoading(slots, pointsRef.current.length));
      }
    }
  }, [notify, removePointAt]);

  const fetchSegment = useCallback(
    (from, to) => enqueue(() => loadSegment(from, to)),
    [enqueue, loadSegment],
  );
  const fetchSegmentRef = useRef(fetchSegment);
  fetchSegmentRef.current = fetchSegment;

  const probeFirstPoint = useCallback(async (point) => {
    const seen = epochRef.current;
    const probe = await loadLeg(point, point);
    if (epochRef.current !== seen || probe?.reject !== "on_land") return;
    // Undone while the probe was out: the point is gone, say nothing.
    if (!pointsRef.current.includes(point)) return;
    if (pointsRef.current.length === 1 && pointsRef.current[0] === point) {
      pointsRef.current = [];
      segmentsRef.current = [];
      setDrawnPoints([]);
      setDrawnSegments([]);
      publishDrawn([], []);
    }
    notify("on_land");
  }, [notify]);

  const addPoint = useCallback((lat, lon, extra) => {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return Promise.resolve();
    if (pointsRef.current.length >= DRAW_MAX_POINTS) {
      notify("limit");
      return Promise.resolve();
    }
    const newPoint = { lat, lon };
    if (extra?.name) newPoint.name = extra.name;
    if (extra?.flags) newPoint.flags = extra.flags;
    const updated = [...pointsRef.current, newPoint];
    pointsRef.current = updated;
    undonePointsRef.current = [];
    undoneSegmentsRef.current = [];
    setCanRedo(false);
    setDrawnPoints([...updated]);
    publishDrawn(updated, segmentsRef.current);
    if (updated.length >= DRAW_MAX_POINTS) notify("limit");
    if (updated.length >= 2) return fetchSegment(updated[updated.length - 2], newPoint);
    // Not queued: a slow probe must not hold back the next legs.
    probeFirstPoint(newPoint).catch(() => {});
    return Promise.resolve();
  }, [fetchSegment, notify, probeFirstPoint]);

  const importPoints = useCallback(
    (points) => importPointsSequential(addPoint, reset, points),
    [addPoint, reset],
  );

  // ↶ removes the last point and its leg only. Legs still loading for earlier
  // points carry on; the removed leg's late answer is ignored (slot generation).
  const undo = useCallback(() => {
    if (!pointsRef.current.length) return;
    const slot = pointsRef.current.length - 2;
    if (slot >= 0) slotGenRef.current[slot] = (slotGenRef.current[slot] || 0) + 1;
    undonePointsRef.current = [...undonePointsRef.current, pointsRef.current.at(-1)];
    undoneSegmentsRef.current = [...undoneSegmentsRef.current, slot >= 0 ? segmentsRef.current[slot] || null : null];
    pointsRef.current = pointsRef.current.slice(0, -1);
    segmentsRef.current = segmentsRef.current.slice(0, Math.max(0, pointsRef.current.length - 1));
    setDrawnPoints([...pointsRef.current]);
    setDrawnSegments(denseSegments(segmentsRef.current));
    publishDrawn(pointsRef.current, segmentsRef.current);
    // Only the undone leg stops counting: earlier legs still loading keep the spinner.
    setDrawingLoading(legsStillLoading(pendingSlotsRef.current, pointsRef.current.length));
    setCanRedo(true);
  }, []);

  const redo = useCallback(() => {
    if (!undonePointsRef.current.length) return;
    const restoredPoint = undonePointsRef.current.at(-1);
    const restoredSegment = undoneSegmentsRef.current.at(-1) || null;
    undonePointsRef.current = undonePointsRef.current.slice(0, -1);
    undoneSegmentsRef.current = undoneSegmentsRef.current.slice(0, -1);
    pointsRef.current = [...pointsRef.current, restoredPoint];
    const slot = pointsRef.current.length - 2;
    const from = slot >= 0 ? pointsRef.current[slot] : null;
    if (from && restoredSegment && restoredSegment.from === from) {
      const next = segmentsRef.current.slice(0, slot);
      next[slot] = restoredSegment;
      segmentsRef.current = next;
    }
    setDrawnPoints([...pointsRef.current]);
    setDrawnSegments(denseSegments(segmentsRef.current));
    publishDrawn(pointsRef.current, segmentsRef.current);
    setCanRedo(undonePointsRef.current.length > 0);
    // The leg was still loading when it was undone: fetch it again.
    if (from && !(restoredSegment && restoredSegment.from === from)) {
      fetchSegment(from, restoredPoint).catch(() => {});
    }
  }, [fetchSegment]);

  /** Rename / flag a placed point (satellite popup « point info »). */
  const updatePoint = useCallback((index, patch) => {
    const updated = [...pointsRef.current];
    if (!updated[index]) return;
    updated[index] = { ...updated[index], ...patch };
    pointsRef.current = updated;
    setDrawnPoints([...updated]);
    publishDrawn(updated, segmentsRef.current);
  }, []);

  /** The drawn route as the GeoJSON the plan endpoint expects. */
  const toGeoJson = useCallback(() => {
    const lineFeatures = denseSegments(segmentsRef.current).filter((s) => s.coords?.length > 0).map((s) => ({
      type: "Feature",
      properties: Number.isFinite(s.nm) ? { nm: s.nm } : {},
      geometry: { type: "LineString", coordinates: s.coords },
    }));
    const pointFeatures = pointsRef.current.map((p, i) => ({
      type: "Feature",
      properties: { name: p.name || `Point ${i + 1}`, flags: p.flags || [], naviguide_type: "drawn_waypoint" },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    }));
    return { type: "FeatureCollection", features: [...lineFeatures, ...pointFeatures] };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    window.__naviguideAddDrawnPoint = addPoint;
    return () => {
      if (window.__naviguideAddDrawnPoint === addPoint) delete window.__naviguideAddDrawnPoint;
    };
  }, [addPoint]);

  return {
    drawingMode, setDrawingMode,
    drawnPoints, drawnSegments, drawingLoading, drawingNotice, canRedo,
    reset, addPoint, importPoints, undo, redo, updatePoint, toGeoJson,
  };
}
