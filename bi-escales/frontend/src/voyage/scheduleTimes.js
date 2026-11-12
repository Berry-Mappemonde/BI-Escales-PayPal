/**
 * Puts the simulated voyage clock on the schedule's times.
 *
 * The clock built from the route (voyageClock.js) starts the sea leg at La
 * Rochelle at t0 and gives the overland leg from Saint-Maur no time at all. The
 * API schedule (`/api/escales/schedule`, from NAVIGUIDE's cabin table) gives
 * that leg its own hours, so every stop after Saint-Maur is reached later there
 * than in the simulation. Stop statuses, the next stop and the Captain all
 * follow the schedule; this keeps the boat, the miles and the ETAs on it too.
 *
 * Each stop found in both gives two anchors (arrival, departure) pairing a
 * simulated time with the schedule's. Every vertex of the clock is moved
 * between its two surrounding anchors, keeping its place in proportion: by time
 * at sea, or by distance where the simulation spends no time (overland).
 */
import { isoFromT0 } from "./voyageClock.js";
import { stopTimeline } from "./stopStatus.js";

const HOUR_MS = 3_600_000;
const EPS = 1e-6;
// The clock finds a stop's mark within this distance along the route (voyageClock.js).
const MARK_TOLERANCE_NM = 0.45;

function moment(iso) {
  const ms = Date.parse(String(iso ?? ""));
  return Number.isNaN(ms) ? null : ms;
}

function filmOf(point) {
  const film = Number(point?.filmNm ?? point?.nm);
  return Number.isFinite(film) ? film : null;
}

/** Anchors in route order: `{ film, sim, real }`, hours after t0, all three never going back. */
export function scheduleAnchors(clock, stops, schedule) {
  const t0 = moment(clock?.t0);
  const rows = schedule?.export?.escales || [];
  if (t0 === null || !rows.length) return [];
  const anchors = [];
  for (const stop of stops || []) {
    const film = filmOf(stop);
    const row = rows.find((r) => r?.milestone_id && r.milestone_id === stop?.milestoneId);
    const arrival = moment(row?.arrival_iso);
    const mark = film === null
      ? null
      : (clock.marks || []).find((m) => Math.abs(filmOf(m) - film) <= MARK_TOLERANCE_NM);
    if (arrival === null || !mark || !Number.isFinite(Number(mark.tHours))) continue;
    const sim = Number(mark.tHours);
    anchors.push({ film, sim, real: (arrival - t0) / HOUR_MS, side: "arrival" });
    const departure = moment(stopTimeline(schedule, stop).departureIso);
    if (departure !== null && departure >= arrival) {
      anchors.push({
        film,
        sim: sim + (Number(mark.holdHours) || 0),
        real: (departure - t0) / HOUR_MS,
        side: "departure",
      });
    }
  }
  const kept = [];
  for (const anchor of anchors) {
    const last = kept[kept.length - 1];
    if (!last || (anchor.film >= last.film && anchor.sim >= last.sim && anchor.real >= last.real)) {
      kept.push(anchor);
    }
  }
  return kept;
}

/** Schedule hours for a point of the simulation (distance `film`, simulated hours `sim`). */
export function scheduleHours(film, sim, anchors) {
  if (!anchors.length) return sim;
  let j = -1;
  for (let i = 0; i < anchors.length; i++) {
    const a = anchors[i];
    if (a.sim > sim + EPS) break;
    if (a.film <= film + EPS) j = i;
  }
  if (j < 0) return sim + (anchors[0].real - anchors[0].sim);
  const a = anchors[j];
  const b = anchors[j + 1];
  if (!b) return sim + (a.real - a.sim);
  const clamp = (x) => Math.max(0, Math.min(1, x));
  if (b.sim - a.sim > EPS) return a.real + clamp((sim - a.sim) / (b.sim - a.sim)) * (b.real - a.real);
  if (b.film - a.film > EPS) return a.real + clamp((film - a.film) / (b.film - a.film)) * (b.real - a.real);
  return a.real;
}

/**
 * The same clock, timed by the schedule. Without a usable schedule the clock is
 * returned as it is.
 */
export function alignClockToSchedule(clock, stops, schedule) {
  const anchors = scheduleAnchors(clock, stops, schedule);
  if (!anchors.length || !clock?.vertices?.length) return clock;
  const t0 = clock.t0;

  const vertices = [];
  for (const vertex of clock.vertices) {
    const film = filmOf(vertex) ?? 0;
    const real = scheduleHours(film, Number(vertex.tHours) || 0, anchors);
    // A stop the schedule holds longer than the simulation: the boat arrives at the
    // schedule's arrival and waits at the quay until its departure.
    const held = anchors.find(
      (a, i) =>
        a.side === "departure" &&
        Math.abs(a.film - film) <= EPS &&
        Math.abs(a.real - real) <= EPS &&
        anchors[i - 1]?.side === "arrival" &&
        Math.abs(anchors[i - 1].film - film) <= EPS &&
        anchors[i - 1].real < real - EPS &&
        !vertices.some((v) => Math.abs(filmOf(v) - film) <= EPS),
    );
    if (held) {
      const arrival = anchors[anchors.indexOf(held) - 1].real;
      vertices.push({ ...vertex, tHours: arrival, iso: isoFromT0(t0, arrival) });
      vertices.push({ ...vertex, tHours: real, iso: isoFromT0(t0, real), vehicle: "quay", speedKnots: null, windKnots: null, twa: null });
      continue;
    }
    vertices.push({ ...vertex, tHours: real, iso: isoFromT0(t0, real) });
  }

  const marks = (clock.marks || []).map((mark) => {
    const film = filmOf(mark) ?? 0;
    const here = anchors.filter((a) => Math.abs(a.film - film) <= MARK_TOLERANCE_NM);
    const sim = Number(mark.tHours) || 0;
    const arrival = here.find((a) => a.side === "arrival")?.real ?? scheduleHours(film, sim, anchors);
    const departure =
      here.find((a) => a.side === "departure")?.real ??
      scheduleHours(film, sim + (Number(mark.holdHours) || 0), anchors);
    return { ...mark, tHours: arrival, iso: isoFromT0(t0, arrival), holdHours: Math.max(0, departure - arrival) };
  });

  const lastNonQuay = [...vertices].reverse().find((v) => v.vehicle !== "quay") || vertices[vertices.length - 1];
  return { ...clock, vertices, marks, arrivalIso: lastNonQuay?.iso ?? clock.arrivalIso, scheduleAligned: true };
}
