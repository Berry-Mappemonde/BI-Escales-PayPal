import { describe, expect, it } from "vitest";
import { nextOpenStop } from "./nextStop.js";

const stops = [
  { name: "Saint-Maur (Berry, Indre)", milestoneId: "dep-saint-maur-berry-indre" },
  { name: "La Rochelle", milestoneId: "dep-la-rochelle" },
  { name: "Ajaccio (Corse)", milestoneId: "dep-ajaccio-corse" },
];

const schedule = {
  export: {
    escales: [
      { milestone_id: "dep-saint-maur-berry-indre", arrival_iso: "2026-11-12T08:00:00+00:00" },
      { milestone_id: "dep-la-rochelle", arrival_iso: "2026-11-12T12:00:00+00:00" },
      { milestone_id: "dep-ajaccio-corse", arrival_iso: "2026-11-29T02:02:52+00:00" },
    ],
  },
  legs: [
    { from_milestone_id: "dep-saint-maur-berry-indre", to_milestone_id: "dep-la-rochelle", departure_iso: "2026-11-12T08:00:00+00:00" },
    { from_milestone_id: "dep-la-rochelle", to_milestone_id: "dep-ajaccio-corse", departure_iso: "2026-11-12T12:00:00+00:00" },
  ],
};

const name = (now, milestones) => nextOpenStop(stops, schedule, now, milestones)?.name ?? null;

describe("nextOpenStop", () => {
  it("is the first stop before departure day", () => {
    expect(name("2026-11-10T19:00:00Z")).toBe("Saint-Maur (Berry, Indre)");
  });

  it("skips a stop whose scheduled arrival has passed: La Rochelle, not Saint-Maur", () => {
    expect(name("2026-11-12T10:00:00+00:00")).toBe("La Rochelle");
  });

  it("counts a stop as arrived from its scheduled arrival, like the sheet's chip", () => {
    expect(name("2026-11-12T08:00:00+00:00")).toBe("La Rochelle");
    expect(name("2026-11-12T12:00:00+00:00")).toBe("Ajaccio (Corse)");
  });

  it("skips a cancelled stop", () => {
    const milestones = [{ id: "dep-la-rochelle", evidence: [], meta: { cancelled: true } }];
    expect(name("2026-11-12T10:00:00Z", milestones)).toBe("Ajaccio (Corse)");
  });

  it("returns nothing once every stop is behind the boat", () => {
    expect(name("2027-12-01T00:00:00Z")).toBeNull();
  });

  it("returns nothing without a clock or a schedule, rather than guessing", () => {
    expect(name(null)).toBeNull();
    expect(nextOpenStop(stops, null, "2026-11-12T10:00:00Z", null)).toBeNull();
    expect(nextOpenStop(null, schedule, "2026-11-12T10:00:00Z", null)).toBeNull();
  });

  it("looks at each milestone once when the route lists a stop twice", () => {
    const twice = [stops[0], stops[0], stops[1]];
    expect(nextOpenStop(twice, schedule, "2026-11-12T10:00:00Z", null)?.name).toBe("La Rochelle");
  });
});
