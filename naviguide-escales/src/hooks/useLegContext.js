/**
 * useLegContext — geometric calculation of the active leg
 *
 * Snap-to-route: manual haversine projection onto each polyline segment.
 * No API call, no external dependency (no @turf).
 *
 * The simulationStep parameter constrains the snap to the chronologically
 * correct portion of the polyline, avoiding ambiguities when the itinerary
 * passes twice through the same geographic area (e.g. Cape Verde outbound vs return).
 *
 * The stops→polyline mapping is monotonic (index[i] ≥ index[i-1]) so
 * chronological order is kept even when two stops share the same coordinates.
 *
 * Returns LegContext:
 *   fromStopIndex     — index of the origin point (stopover or intermediate)
 *   fromStop          — name of the origin point
 *   toStop            — name of the next point (stopover or intermediate)
 *   toStopIndex       — index of the next point
 *   nmCovered         — nautical miles covered since departure (full route)
 *   nmRemainingToStop — nautical miles remaining to the next point
 *   etaHours          — estimated ETA (default constant speed)
 *   bearing           — current heading in degrees (0–360)
 *   snappedPosition   — [lon, lat] — position projected onto the route
 */

import { useMemo } from "react";
import { chapterAtNm } from "../engine/routePlayhead.js";
import { sampleClockAtTime } from "../engine/voyageClock.js";
import { nextEscaleStop } from "../utils/escales.js";

// Default catamaran speed (knots)
const DEFAULT_SPEED_KNOTS = 7;

// ── Haversine ────────────────────────────────────────────────────────────────

const R_NM = 3440.065; // Earth radius in nautical miles

function toRad(deg) { return (deg * Math.PI) / 180; }

function haversineNm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.sqrt(a));
}

/**
 * Initial bearing between two geodesic points, in degrees (0–360).
 */
function initialBearing(lat1, lon1, lat2, lon2) {
  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δλ = toRad(lon2 - lon1);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/**
 * Project point P (lat, lon) onto segment AB.
 * Returns { point: [lon, lat], t: 0..1, distNm } where t=0→A, t=1→B.
 *
 * Planar approximation valid for short segments (< 500 nm).
 */
function projectOnSegment(pLat, pLon, aLat, aLon, bLat, bLon) {
  const dx = bLon - aLon;
  const dy = bLat - aLat;
  const lenSq = dx * dx + dy * dy;

  let t = 0;
  if (lenSq > 0) {
    t = ((pLon - aLon) * dx + (pLat - aLat) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
  }

  const qLon = aLon + t * dx;
  const qLat = aLat + t * dy;
  return { point: [qLon, qLat], t, distNm: haversineNm(pLat, pLon, qLat, qLon) };
}

/**
 * Build a MONOTONIC stops→polyline mapping (index[i] ≥ index[i-1]).
 *
 * Unlike a global nearest-neighbour search, this approach guarantees that
 * two geographically identical stops (e.g. Cape Verde outbound and
 * Cape Verde return) map to different, increasing polyline indexes,
 * so the itinerary chronological order is respected.
 *
 * @param {Array} stops    — ordered list of { lat, lon, name, ... }
 * @param {Array} polyline — array [[lon, lat], ...]
 * @returns {Array} — [{ stop, polyIdx }, ...]
 */
function buildMonotonicStopIndices(stops, polyline) {
  const result = [];
  let searchStart = 0;

  for (const stop of stops) {
    let best = searchStart;
    let bestD = Infinity;
    // Search only from searchStart (guarantees monotonicity)
    for (let i = searchStart; i < polyline.length; i++) {
      const [pLon, pLat] = polyline[i];
      const d = haversineNm(stop.lat, stop.lon, pLat, pLon);
      if (d < bestD) { bestD = d; best = i; }
    }
    result.push({ stop, polyIdx: best });
    searchStart = best; // the next stop must be beyond this point
  }

  return result;
}

/**
 * Leg at the official clock instant `now`.
 * The playback cursor and the clock start (t0) are ignored: only the sample
 * at `now` chooses the chapter.
 */
export function legAtClockNow({
  clock,
  now = Date.now(),
  marks = null,
  cursor = null,
  t0 = null,
  speedKnots = null,
} = {}) {
  void cursor;
  void t0;
  const sample = sampleClockAtTime(clock, now);
  if (!sample) return null;
  const chapterMarks = (marks && marks.length) ? marks : (clock?.marks || []);
  const sailNm = Number(sample.sailNm);
  if (!chapterMarks.length || !Number.isFinite(sailNm)) return null;
  const chapter = chapterAtNm(chapterMarks, sailNm);
  const destNm = Number(chapter.to?.nm);
  const remaining = chapter.finished
    ? 0
    : (Number.isFinite(destNm) ? Math.max(0, destNm - sailNm) : null);
  const asked = Number(speedKnots);
  const sampled = Number(sample.speedKnots);
  const knots = Number.isFinite(asked) && asked > 0
    ? asked
    : (Number.isFinite(sampled) && sampled > 0 ? sampled : null);
  const sea = Number(sample.seaHours);
  const day = Number.isFinite(sea) && sea > 0 ? Math.floor(sea / 24) + 1 : null;
  const fromStop = chapter.from?.name || null;
  const toStop = chapter.finished
    ? (chapter.from?.name || null)
    : (chapter.to?.name || null);
  return {
    fromStop,
    toStop,
    fromStopIndex: chapter.fromIdx,
    toStopIndex: chapter.toIdx,
    nmCovered: Math.round(Math.max(0, sailNm)),
    nmRemainingToStop: remaining == null ? null : Math.round(remaining),
    remainingNm: remaining,
    etaHours: knots && remaining != null ? remaining / knots : null,
    bearing: Number.isFinite(Number(sample.bearing)) ? Math.round(Number(sample.bearing)) : null,
    snappedPosition: Number.isFinite(Number(sample.lon)) && Number.isFinite(Number(sample.lat))
      ? [Number(sample.lon), Number(sample.lat)]
      : null,
    speedKnots: knots == null ? null : Math.round(knots * 10) / 10,
    finished: Boolean(chapter.finished),
    chapter,
    day,
    lat: sample.lat,
    lon: sample.lon,
    iso: sample.iso,
    sailNm,
  };
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * @param {number|null} catamaranLat    — catamaran latitude (null if not enabled)
 * @param {number|null} catamaranLon    — catamaran longitude
 * @param {Array}       routeSegments   — segments computed by App.jsx [ {coords: [[lon,lat],...], nonMaritime?} ]
 * @param {Array}       itineraryPoints — ITINERARY_POINTS (stopovers + intermediate points)
 * @param {number}      speedKnots      — speed in knots (optional)
 * @param {number|null} simulationStep  — index in simTargets (constrains snap to the right portion)
 *
 * simTargets layout (generated by App.jsx):
 *   step 0            → start = beginning of maritime segment 0
 *   step 2k+1, k ≥ 0 → midpoint of maritime segment k
 *   step 2k+2, k ≥ 0 → end      of maritime segment k
 * So: maritimeSegIdx = (step === 0) ? 0 : Math.floor((step - 1) / 2)
 */
export function useLegContext(
  catamaranLat,
  catamaranLon,
  routeSegments,
  itineraryPoints,
  speedKnots = DEFAULT_SPEED_KNOTS,
  simulationStep = null,
) {
  return useMemo(() => {
    if (catamaranLat == null || catamaranLon == null) return null;
    if (!routeSegments || routeSegments.length === 0) return null;

    // ── 1. Flatten route segments + remember start indexes per segment ─
    const polyline = [];
    // segPolyStart[i] = index in polyline where routeSegments[i] starts
    const segPolyStart = [];

    for (let si = 0; si < routeSegments.length; si++) {
      const seg = routeSegments[si];
      segPolyStart.push(polyline.length); // recorded BEFORE adding coords
      if (!seg.coords || seg.coords.length < 2) continue;
      if (polyline.length === 0) {
        polyline.push(...seg.coords);
      } else {
        // Skip first point of subsequent segments (duplicate junction)
        polyline.push(...seg.coords.slice(1));
      }
    }
    if (polyline.length < 2) return null;

    // ── 2. Snap window constrained by simulationStep ─────────────────────
    // When simulationStep is known, nearest-segment search is restricted to
    // the polyline portion of the current maritime leg (± 1 leg of tolerance).
    // This stops the snap from jumping onto a geographically close but
    // chronologically different leg.
    let snapWinStart = 0;
    let snapWinEnd   = polyline.length - 1;

    if (simulationStep !== null) {
      // Indexes of valid maritime segments in routeSegments
      const maritimeSegIndices = routeSegments
        .map((seg, i) => ({ seg, i }))
        .filter(({ seg }) => !seg.nonMaritime && seg.coords?.length >= 2)
        .map(({ i }) => i);

      if (maritimeSegIndices.length > 0) {
        // Maritime segment matching simulationStep
        const msi = Math.min(
          simulationStep === 0 ? 0 : Math.floor((simulationStep - 1) / 2),
          maritimeSegIndices.length - 1,
        );

        // ±1 maritime-leg tolerance for smooth transitions
        const msiFrom = Math.max(0, msi - 1);
        const msiTo   = Math.min(maritimeSegIndices.length - 1, msi + 1);

        const segIdxFrom = maritimeSegIndices[msiFrom];
        const segIdxTo   = maritimeSegIndices[msiTo];

        // Step back one point to include the incoming junction
        snapWinStart = Math.max(0, segPolyStart[segIdxFrom] - 1);

        // Stop at the start of the next segment (outgoing junction included)
        snapWinEnd = (segIdxTo + 1 < routeSegments.length)
          ? segPolyStart[segIdxTo + 1]
          : polyline.length - 1;

        snapWinStart = Math.max(0, snapWinStart);
        snapWinEnd   = Math.min(polyline.length - 1, snapWinEnd);
      }
    }

    // ── 3. Snap the catamaran onto the constrained window ───────────────────────────
    let bestDist   = Infinity;
    let bestSnap   = null;
    let bestSegIdx = snapWinStart;
    let bestT      = 0;

    for (let i = snapWinStart; i < snapWinEnd && i < polyline.length - 1; i++) {
      const [aLon, aLat] = polyline[i];
      const [bLon, bLat] = polyline[i + 1];
      const res = projectOnSegment(catamaranLat, catamaranLon, aLat, aLon, bLat, bLon);
      if (res.distNm < bestDist) {
        bestDist   = res.distNm;
        bestSnap   = res.point; // [lon, lat]
        bestSegIdx = i;
        bestT      = res.t;
      }
    }

    if (!bestSnap) return null;
    const [snapLon, snapLat] = bestSnap;

    // ── 4. Cumulative nautical miles from departure to the snap ────────────
    let nmCoveredTotal = 0;
    for (let i = 0; i < bestSegIdx; i++) {
      const [aLon, aLat] = polyline[i];
      const [bLon, bLat] = polyline[i + 1];
      nmCoveredTotal += haversineNm(aLat, aLon, bLat, bLon);
    }
    // Partial remainder of the active segment
    const [aLon, aLat] = polyline[bestSegIdx];
    const [bLon, bLat] = polyline[bestSegIdx + 1];
    nmCoveredTotal += bestT * haversineNm(aLat, aLon, bLat, bLon);

    // ── 5. Identify the active leg (segment from/to) ───────────────
    // Use the segment that contains bestSegIdx directly: the route has repeated
    // stops (Halifax, Cayenne) so buildMonotonicStopIndices yields false positives
    // (e.g. SPM→Papeete instead of SPM→Halifax). The active segment has the right from/to.
    let fromStop = null;
    let toStop   = null;
    let fromIdx  = 0;
    let toIdx    = 0;
    let useSegmentBased = false;

    let activeSegIdx = 0;
    for (let si = 0; si < routeSegments.length; si++) {
      const end = segPolyStart[si + 1] ?? polyline.length;
      if (bestSegIdx < end) {
        activeSegIdx = si;
        break;
      }
    }
    const activeSeg = routeSegments[activeSegIdx];
    const stops = (itineraryPoints || []);
    const stopIndices = buildMonotonicStopIndices(stops, polyline);

    if (activeSeg?.from?.name && activeSeg?.to?.name) {
      useSegmentBased = true;
      fromStop = activeSeg.from;
      toStop   = activeSeg.to;
      fromIdx = stopIndices.findIndex((s) => s.stop?.name === fromStop?.name);
      toIdx   = stopIndices.findIndex((s) => s.stop?.name === toStop?.name);
      if (fromIdx < 0) fromIdx = 0;
      if (toIdx < 0) toIdx = Math.max(0, fromIdx + 1);
    } else {
      fromStop = stopIndices[0]?.stop;
      toStop   = stopIndices[stopIndices.length - 1]?.stop;
      fromIdx  = 0;
      toIdx    = stopIndices.length - 1;
      for (let i = 0; i < stopIndices.length; i++) {
        if (stopIndices[i].polyIdx > bestSegIdx) {
          toStop   = stopIndices[i].stop;
          toIdx    = i;
          fromStop = i > 0 ? stopIndices[i - 1].stop : null;
          fromIdx  = i > 0 ? i - 1 : 0;
          break;
        }
      }
    }

    // Briefing destination = next stopover, never an intermediate point
    if (toStop && !toStop.flag) {
      const resolved = nextEscaleStop(stops, toIdx);
      if (resolved.stop) {
        toStop = resolved.stop;
        toIdx = resolved.index;
      }
    }

    // ── 6. Nautical miles remaining to the next stop ───────────────────
    const toStopPolyIdx = useSegmentBased
      ? (segPolyStart[activeSegIdx + 1] ?? polyline.length) - 1
      : (stopIndices[toIdx]?.polyIdx ?? polyline.length - 1);
    let nmRemainingToStop = 0;
    if (toStopPolyIdx > bestSegIdx) {
      // Remaining portion of the active segment
      nmRemainingToStop += (1 - bestT) * haversineNm(aLat, aLon, bLat, bLon);
      // Full segments through to the target stop
      for (let i = bestSegIdx + 1; i < toStopPolyIdx; i++) {
        const [cLon, cLat] = polyline[i];
        const [dLon, dLat] = polyline[i + 1];
        nmRemainingToStop += haversineNm(cLat, cLon, dLat, dLon);
      }
    }

    // ── 7. Bearing (heading) ─────────────────────────────────────────────────────
    // When the snap is at the end of a segment (t≈1, catamaran exactly on a
    // stopover/junction), advance one segment to show the DEPARTURE heading
    // rather than the ARRIVAL heading. Example: catamaran AT Avant Corse must
    // show the heading toward Ajaccio (NNE), not the approach from La Rochelle.
    let bearingSegIdx = bestSegIdx;
    if (bestT > 0.999 && bearingSegIdx + 1 < polyline.length - 1) {
      bearingSegIdx += 1;
    }
    const [bearALon, bearALat] = polyline[bearingSegIdx];
    const [bearBLon, bearBLat] = polyline[bearingSegIdx + 1];
    const bearing = initialBearing(bearALat, bearALon, bearBLat, bearBLon);

    // ── 8. ETA ───────────────────────────────────────────────────────────────
    const etaHours = speedKnots > 0 ? nmRemainingToStop / speedKnots : 0;

    return {
      fromStopIndex:     fromIdx,
      fromStop:          fromStop?.name ?? "Départ",
      toStopIndex:       toIdx,
      toStop:            toStop?.name  ?? "Arrivée",
      nmCovered:         Math.round(nmCoveredTotal),
      nmRemainingToStop: Math.round(nmRemainingToStop),
      etaHours:          Math.round(etaHours),
      bearing:           Math.round(bearing),
      snappedPosition:   [snapLon, snapLat],
      speedKnots,
    };
  }, [catamaranLat, catamaranLon, routeSegments, itineraryPoints, speedKnots, simulationStep]);
}
