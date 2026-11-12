/**
 * The boat on the map follows the API schedule. Real data only: the public route
 * file and the schedule test2 served on 12 Nov 2026 (fixtures/).
 */
import { describe, expect, it } from "vitest";
import routeText from "../../public/route.geojson?raw";
import { PRODUCTION_T0_ISO } from "./departureT0.js";
import { sampleAt, voyageFromRoute } from "./loadVoyage.js";
import { boatPosition } from "./boatPosition.js";
import { scheduleAnchors } from "./scheduleTimes.js";
import { stopStatus, stopTimeline } from "./stopStatus.js";
import schedule from "./fixtures/schedule-test2-2026-11-12.json";

const route = JSON.parse(routeText);
const HOUR = 3_600_000;
const at = (iso) => new Date(iso);
const plusHours = (iso, hours) => new Date(Date.parse(iso) + hours * HOUR);
const escale = (id) => schedule.export.escales.find((row) => row.milestone_id === id);

const simulated = voyageFromRoute(route, PRODUCTION_T0_ISO);
const aligned = voyageFromRoute(route, PRODUCTION_T0_ISO, schedule);
const laRochelle = aligned.stops.find((stop) => stop.milestoneId === "dep-la-rochelle");

describe("the simulated clock on the schedule's times", () => {
  it("starts from the cause: alone, the simulation sails from La Rochelle 4 h before the schedule", () => {
    const sample = sampleAt(simulated.clock, at("2026-11-12T10:00:00Z"));
    expect(sample.filmNm).toBeGreaterThan(laRochelle.filmNm);
    expect(escale("dep-la-rochelle").arrival_iso).toBe("2026-11-12T12:00:00+00:00");
  });

  it("reaches every stop at the schedule's arrival and leaves at its departure", () => {
    for (const stop of aligned.stops) {
      const row = escale(stop.milestoneId);
      const mark = aligned.clock.marks.find((m) => Math.abs(m.filmNm - stop.filmNm) <= 0.45);
      if (!row || !mark) continue;
      expect(Math.abs(Date.parse(mark.iso) - Date.parse(row.arrival_iso)), stop.name).toBeLessThan(1000);
      const departure = stopTimeline(schedule, stop).departureIso;
      if (departure) {
        const leaves = Date.parse(mark.iso) + mark.holdHours * HOUR;
        expect(Math.abs(leaves - Date.parse(departure)), stop.name).toBeLessThan(1000);
      }
    }
    expect(scheduleAnchors(simulated.clock, simulated.stops, schedule).length).toBeGreaterThan(20);
  });

  it("drives overland from Saint-Maur from 08:00 and is at La Rochelle at 12:00", () => {
    const leaving = sampleAt(aligned.clock, at("2026-11-12T08:00:00Z"));
    expect(leaving.filmNm).toBe(0);
    const halfway = sampleAt(aligned.clock, at("2026-11-12T10:00:00Z"));
    expect(halfway.filmNm).toBeGreaterThan(0);
    expect(halfway.filmNm).toBeLessThan(laRochelle.filmNm);
    const there = sampleAt(aligned.clock, at("2026-11-12T12:00:00Z"));
    expect(there.filmNm).toBeCloseTo(laRochelle.filmNm, 1);
    expect(there.iso).toBe("2026-11-12T12:00:00.000Z");
  });

  it("keeps the boat at Ajaccio's quay for the schedule's three days", () => {
    const row = escale("dep-ajaccio-corse");
    const sample = sampleAt(aligned.clock, plusHours(row.arrival_iso, 24));
    expect(sample.atQuay).toBe(true);
    expect(boatPosition(aligned.stops, sample)).toEqual({ kind: "stop", stop: "Ajaccio (Corse)" });
  });

  it("ends the voyage when the schedule's last leg arrives", () => {
    const last = schedule.legs[schedule.legs.length - 1];
    expect(Math.abs(Date.parse(aligned.clock.arrivalIso) - Date.parse(last.arrival_iso))).toBeLessThan(1000);
  });

  it("leaves the clock as it is without a schedule", () => {
    expect(voyageFromRoute(route, PRODUCTION_T0_ISO, null).clock).toEqual(simulated.clock);
    expect(voyageFromRoute(route, PRODUCTION_T0_ISO, { legs: [], export: { escales: [] } }).clock).toEqual(
      simulated.clock,
    );
  });

  it("waits at the quay when the schedule holds a stop the simulation does not", () => {
    // The real schedule, with La Rochelle's departure moved two days later.
    const held = structuredClone(schedule);
    const leg = held.legs.find((l) => l.from_name === "La Rochelle");
    leg.departure_iso = "2026-11-14T12:00:00+00:00";
    const voyage = voyageFromRoute(route, PRODUCTION_T0_ISO, held);
    const during = sampleAt(voyage.clock, at("2026-11-13T12:00:00Z"));
    expect(during.filmNm).toBeCloseTo(laRochelle.filmNm, 1);
    expect(during.atQuay).toBe(true);
    const after = sampleAt(voyage.clock, at("2026-11-14T14:00:00Z"));
    expect(after.filmNm).toBeGreaterThan(laRochelle.filmNm);
  });
});

/**
 * What the schedule alone says, by the stop panel's rules: a stop is reached at its
 * arrival and left at its outbound leg's departure. Null where the schedule gives
 * no departure (Saint-Pierre: the Cayenne → Papeete cabin leg passes it).
 */
// The schedule calls the last stop "La Rochelle (retour)"; the route, "La Rochelle".
const routeName = (name) => name.replace(/ \(retour\)$/, "");
const byArrival = [...schedule.export.escales].sort((a, b) => Date.parse(a.arrival_iso) - Date.parse(b.arrival_iso));

function fromSchedule(when) {
  const reached = byArrival.filter((row) => Date.parse(row.arrival_iso) <= when.getTime());
  if (!reached.length) return { kind: "waiting", stop: byArrival[0].name };
  const here = reached[reached.length - 1];
  const next = byArrival[reached.length];
  if (!next) return { kind: "stop", stop: routeName(here.name) };
  const departure = stopTimeline(schedule, { milestoneId: here.milestone_id, name: here.name }).departureIso;
  if (!departure) return null;
  return when.getTime() < Date.parse(departure)
    ? { kind: "stop", stop: routeName(here.name) }
    : { kind: "underway", from: routeName(here.name), to: routeName(next.name) };
}

/** The stop panel's status for a stop named on the rail: the occurrence reached, or the one ahead. */
function statusOf(name, when, { ahead = false } = {}) {
  const rows = byArrival.filter((r) => routeName(r.name) === name);
  const row = ahead
    ? rows.find((r) => Date.parse(r.arrival_iso) > when.getTime()) ?? rows[rows.length - 1]
    : [...rows].reverse().find((r) => Date.parse(r.arrival_iso) <= when.getTime()) ?? rows[0];
  const { startIso } = stopTimeline(schedule, { milestoneId: row.milestone_id, name: row.name });
  return stopStatus({ now: when.toISOString(), arrivalIso: row.arrival_iso, startIso, cancelled: false });
}

describe("the rail, the map and the stop panel say the same thing", () => {
  const moments = [];
  for (const stop of aligned.stops) {
    const row = escale(stop.milestoneId);
    if (!row) continue;
    moments.push(plusHours(row.arrival_iso, -1), plusHours(row.arrival_iso, 1));
    const departure = stopTimeline(schedule, stop).departureIso;
    if (departure) moments.push(plusHours(departure, -1), plusHours(departure, 1));
  }
  for (let h = 0; h <= 30 * 24; h += 6) moments.push(plusHours("2026-11-12T08:00:00Z", h));

  it("at every stop's arrival and departure, and every 6 hours of the first month", () => {
    let compared = 0;
    for (const when of moments) {
      const expected = fromSchedule(when);
      if (!expected) continue;
      const fromMap = boatPosition(aligned.stops, sampleAt(aligned.clock, when));
      expect(fromMap, when.toISOString()).toEqual(expected);
      compared += 1;
    }
    expect(compared).toBeGreaterThan(150);
  });

  it("never says under way to a stop the panel calls reached, or at a stop it has not reached", () => {
    for (const when of moments) {
      const where = boatPosition(aligned.stops, sampleAt(aligned.clock, when));
      if (where.kind === "underway") {
        expect(statusOf(where.from, when), when.toISOString()).toBe("arrived");
        expect(statusOf(where.to, when, { ahead: true }), when.toISOString()).toBe("en_route");
      } else if (where.kind === "stop") {
        expect(statusOf(where.stop, when), when.toISOString()).toBe("arrived");
      }
    }
  });

  it("on the hosted demo's pinned clock (12 Nov 08:00) and the two days after", () => {
    const line = (iso) => boatPosition(aligned.stops, sampleAt(aligned.clock, at(iso)));
    expect(line("2026-11-12T08:00:00Z")).toEqual({ kind: "underway", from: "Saint-Maur (Berry, Indre)", to: "La Rochelle" });
    expect(line("2026-11-12T11:00:00Z")).toEqual({ kind: "underway", from: "Saint-Maur (Berry, Indre)", to: "La Rochelle" });
    expect(line("2026-11-13T08:00:00Z")).toEqual({ kind: "underway", from: "La Rochelle", to: "Ajaccio (Corse)" });
    expect(statusOf("La Rochelle", at("2026-11-12T11:00:00Z"))).toBe("en_route");
  });

  it("sails the last leg toward La Rochelle and ends there", () => {
    const leg = schedule.legs[schedule.legs.length - 1];
    const line = (when) => boatPosition(aligned.stops, sampleAt(aligned.clock, when));
    expect(line(plusHours(leg.departure_iso, 24))).toEqual({ kind: "underway", from: "Europa (TAAF)", to: "La Rochelle" });
    expect(line(plusHours(leg.arrival_iso, 24))).toEqual({ kind: "stop", stop: "La Rochelle" });
  });

  it("holds the boat at Saint-Pierre as NAVIGUIDE's clock does, where the schedule gives no departure", () => {
    const row = escale("dep-saint-pierre-saint-pierre-et-miquelon");
    expect(stopTimeline(schedule, { milestoneId: row.milestone_id, name: row.name }).departureIso).toBe("");
    const where = boatPosition(aligned.stops, sampleAt(aligned.clock, plusHours(row.arrival_iso, 24)));
    expect(where).toEqual({ kind: "stop", stop: row.name });
  });
});
