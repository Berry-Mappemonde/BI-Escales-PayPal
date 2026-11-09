import { describe, expect, it } from "vitest";
import { departurePlusDays } from "./scheduleClock.testHelper.js";
import {
  formatEurAmount,
  formatScheduleDate,
  fundTotals,
  isMilestoneCancelled,
  logbookLine,
  logbookUpTo,
  stopStatus,
  stopTimeline,
} from "./stopStatus.js";

const ARRIVAL = "2026-11-28T22:02:54.002Z";
const START = "2026-11-12T08:00:00.000Z";

describe("stopStatus", () => {
  const at = (now, extra = {}) => stopStatus({ now, arrivalIso: ARRIVAL, startIso: START, cancelled: false, ...extra });

  it("is upcoming before the boat leaves for the stop", () => {
    expect(at("2026-11-05T08:00:00Z")).toBe("upcoming");
    expect(at("2026-11-12T07:59:59Z")).toBe("upcoming");
  });

  it("is en route from the moment the boat leaves", () => {
    expect(at(START)).toBe("en_route");
    expect(at("2026-11-20T08:00:00Z")).toBe("en_route");
  });

  it("is arrived from the scheduled arrival on", () => {
    expect(at(ARRIVAL)).toBe("arrived");
    expect(at("2026-12-20T08:00:00Z")).toBe("arrived");
  });

  it("is cancelled whatever the schedule says", () => {
    expect(at("2026-11-20T08:00:00Z", { cancelled: true })).toBe("cancelled");
    expect(at("2026-12-20T08:00:00Z", { cancelled: true })).toBe("cancelled");
  });

  it("stays upcoming until arrival when nothing says when the boat leaves", () => {
    expect(at("2026-11-20T08:00:00Z", { startIso: "" })).toBe("upcoming");
    expect(at(ARRIVAL, { startIso: "" })).toBe("arrived");
  });

  it("says nothing without a clock or an arrival", () => {
    expect(at(null)).toBeNull();
    expect(at("not a date")).toBeNull();
    expect(at(null, { cancelled: true })).toBeNull();
    expect(at("2026-11-20T08:00:00Z", { arrivalIso: "" })).toBeNull();
  });
});

describe("stopTimeline", () => {
  const schedule = {
    export: {
      escales: [
        { milestone_id: "dep-ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: ARRIVAL },
        { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: START },
        { milestone_id: "dep-saint-pierre", name: "Saint-Pierre", arrival_iso: departurePlusDays(200) },
      ],
    },
    legs: [
      {
        id: "leg-la-rochelle-to-ajaccio-corse",
        from_name: "La Rochelle",
        to_name: "Ajaccio (Corse)",
        departure_iso: "2026-11-13T08:00:00Z",
      },
      {
        id: "leg-ajaccio",
        from_milestone_id: "dep-ajaccio-corse",
        from_name: "Renamed",
        to_name: "Fort-de-France",
        departure_iso: "2026-12-01T22:02:54.002Z",
      },
    ],
  };

  it("reads the inbound and outbound legs", () => {
    expect(stopTimeline(schedule, { milestoneId: "dep-ajaccio-corse", name: "Ajaccio (Corse)" })).toEqual({
      startIso: "2026-11-13T08:00:00Z",
      departureIso: "2026-12-01T22:02:54.002Z",
    });
  });

  it("falls back to the previous stop's arrival when there is no inbound leg", () => {
    expect(stopTimeline(schedule, { milestoneId: "dep-saint-pierre", name: "Saint-Pierre" }).startIso).toBe(ARRIVAL);
  });

  it("never calculates a departure the schedule does not give", () => {
    expect(stopTimeline(schedule, { milestoneId: "dep-saint-pierre", name: "Saint-Pierre" }).departureIso).toBe("");
  });

  it("gives the first stop no start at all", () => {
    expect(stopTimeline({ export: schedule.export }, { milestoneId: "dep-la-rochelle", name: "La Rochelle" }).startIso).toBe("");
  });

  it("copes with no schedule", () => {
    expect(stopTimeline(null, { milestoneId: "x", name: "X" })).toEqual({ startIso: "", departureIso: "" });
  });
});

describe("isMilestoneCancelled", () => {
  it("mirrors the server rule", () => {
    expect(isMilestoneCancelled({ evidence: [{ facts: { cancelled: true } }] })).toBe(true);
    expect(isMilestoneCancelled({ evidence: [{ facts: { departed: false } }] })).toBe(true);
    expect(isMilestoneCancelled({ evidence: [], meta: { cancelled: true } })).toBe(true);
  });

  it("reads only the latest evidence", () => {
    expect(isMilestoneCancelled({ evidence: [{ facts: { cancelled: true } }, { facts: { cancelled: false } }] })).toBe(false);
  });

  it("is false when nothing says cancelled", () => {
    expect(isMilestoneCancelled({ evidence: [{ facts: { departed: true } }], meta: {} })).toBe(false);
    expect(isMilestoneCancelled({ evidence: [{ met: true }] })).toBe(false);
    expect(isMilestoneCancelled(undefined)).toBe(false);
  });
});

describe("logbookUpTo", () => {
  const entries = [
    { t: "2026-11-26T22:02:54Z", label_en: "Position" },
    { t: ARRIVAL, label_en: "Arrival" },
    { label_en: "No date" },
  ];

  it("hides entries the clock has not reached", () => {
    expect(logbookUpTo(entries, "2026-11-27T00:00:00Z").map((row) => row.label_en)).toEqual(["Position"]);
    expect(logbookUpTo(entries, ARRIVAL).map((row) => row.label_en)).toEqual(["Position", "Arrival"]);
  });

  it("shows nothing before departure or without a clock", () => {
    expect(logbookUpTo(entries, "2026-11-05T08:00:00Z")).toEqual([]);
    expect(logbookUpTo(entries, null)).toEqual([]);
    expect(logbookUpTo(undefined, ARRIVAL)).toEqual([]);
  });
});

describe("fundTotals", () => {
  it("reads held and captured", () => {
    expect(fundTotals({ authorized_eur: "120.50", captured_eur: "30.00" })).toEqual({ heldEur: 120.5, capturedEur: 30 });
  });

  it("treats zero, missing and redacted the same way", () => {
    expect(fundTotals({ authorized_eur: "0.00", captured_eur: "0.00" })).toEqual({ heldEur: null, capturedEur: null });
    expect(fundTotals({})).toEqual({ heldEur: null, capturedEur: null });
    expect(fundTotals({ authorized_eur: null, captured_eur: "•••" })).toEqual({ heldEur: null, capturedEur: null });
    expect(fundTotals(null)).toEqual({ heldEur: null, capturedEur: null });
  });
});

describe("formatting", () => {
  it("gives the date alone, with no time, in UTC", () => {
    expect(formatScheduleDate(ARRIVAL, "en")).toBe("28 Nov 2026");
    expect(formatScheduleDate(ARRIVAL, "fr")).toBe("28 nov. 2026");
    expect(formatScheduleDate("2026-11-30T23:59:00Z", "en")).toBe("30 Nov 2026");
    expect(formatScheduleDate("", "en")).toBe("");
    expect(formatScheduleDate("nonsense", "en")).toBe("");
  });

  it("drops the cents only on a whole amount", () => {
    expect(formatEurAmount(120, "en")).toBe("€120");
    expect(formatEurAmount(120.5, "en")).toBe("€120.50");
  });

  it("builds a logbook line without a time", () => {
    const line = logbookLine({ t: ARRIVAL, label_en: "Stopover — arrival at Ajaccio" }, "en");
    expect(line).toBe("28 Nov 2026 · Stopover — arrival at Ajaccio");
  });
});
