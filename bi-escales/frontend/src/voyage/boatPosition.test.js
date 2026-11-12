import { describe, expect, it } from "vitest";
import { AT_STOP_TOLERANCE_NM, boatPosition, departureDate, scheduleDepartureIso } from "./boatPosition.js";
import schedule from "./fixtures/schedule-test2-2026-11-12.json";

const stops = [
  { name: "Saint-Maur (Berry, Indre)", filmNm: 0 },
  { name: "La Rochelle", filmNm: 120 },
  { name: "Ajaccio (Corse)", filmNm: 1500 },
];

describe("boatPosition", () => {
  it("says nothing without a sample or without stops", () => {
    expect(boatPosition(stops, null)).toBeNull();
    expect(boatPosition([], { status: "live", filmNm: 10 })).toBeNull();
    expect(boatPosition(stops, { status: "live" })).toBeNull();
  });

  it("waits at the first stop before departure", () => {
    expect(boatPosition(stops, { status: "waiting", atQuay: true, filmNm: 0 })).toEqual({
      kind: "waiting",
      stop: "Saint-Maur (Berry, Indre)",
    });
  });

  it("is under way between the last stop reached and the next one", () => {
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 131.3 })).toEqual({
      kind: "underway",
      from: "La Rochelle",
      to: "Ajaccio (Corse)",
    });
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 60 })).toEqual({
      kind: "underway",
      from: "Saint-Maur (Berry, Indre)",
      to: "La Rochelle",
    });
  });

  it("is at a stop while it is held there", () => {
    expect(boatPosition(stops, { status: "live", atQuay: true, filmNm: 120.2 })).toEqual({
      kind: "stop",
      stop: "La Rochelle",
    });
  });

  it("is at the last stop once the voyage is over", () => {
    expect(boatPosition(stops, { status: "arrived", atQuay: true, filmNm: 1500 })).toEqual({
      kind: "stop",
      stop: "Ajaccio (Corse)",
    });
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 1600 })).toEqual({
      kind: "stop",
      stop: "Ajaccio (Corse)",
    });
  });

  it("uses the sailed distance when a stop has no film distance", () => {
    const plain = [{ name: "A", nm: 0 }, { name: "B", nm: 50 }];
    expect(boatPosition(plain, { status: "live", filmNm: 20 })).toEqual({ kind: "underway", from: "A", to: "B" });
  });

  it("does not name a stop before the boat is on it", () => {
    const justShort = 1500 - AT_STOP_TOLERANCE_NM * 2;
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: justShort })).toEqual({
      kind: "underway",
      from: "La Rochelle",
      to: "Ajaccio (Corse)",
    });
  });

  it("puts the return to La Rochelle at the end of the route, not at its departure point", () => {
    // As in the route file: the last stop has the first La Rochelle's coordinates, so its distance.
    const loop = [...stops, { name: "La Rochelle", filmNm: 120 }];
    expect(boatPosition(loop, { status: "live", atQuay: false, filmNm: 1600 })).toEqual({
      kind: "underway",
      from: "Ajaccio (Corse)",
      to: "La Rochelle",
    });
    expect(boatPosition(loop, { status: "live", atQuay: true, filmNm: 1500 })).toEqual({ kind: "stop", stop: "Ajaccio (Corse)" });
    expect(boatPosition(loop, { status: "arrived", atQuay: true, filmNm: 1700 })).toEqual({ kind: "stop", stop: "La Rochelle" });
  });
});

describe("departureDate", () => {
  it("is the schedule's first departure, the day only", () => {
    expect(departureDate(schedule, "2030-01-01T00:00:00Z", "en")).toBe("12 Nov 2026");
    expect(departureDate(schedule, "2030-01-01T00:00:00Z", "fr")).toBe("12 nov. 2026");
    expect(scheduleDepartureIso(schedule)).toBe("2026-11-12T08:00:00.000Z");
  });

  it("falls back to the clock's departure without a schedule", () => {
    expect(departureDate(null, "2026-11-12T08:00:00.000Z", "en")).toBe("12 Nov 2026");
    expect(departureDate({ legs: [] }, "2026-11-12T08:00:00.000Z", "fr")).toBe("12 nov. 2026");
  });
});
