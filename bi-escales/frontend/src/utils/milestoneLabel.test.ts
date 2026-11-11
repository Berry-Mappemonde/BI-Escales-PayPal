import { describe, expect, it } from "vitest";
import { milestoneLabel, stopNamesFromStops } from "./milestoneLabel";

const stops = [
  { name: "Saint-Maur (Berry, Indre)", milestoneId: "dep-saint-maur-berry-indre" },
  { name: "La Rochelle", milestoneId: "dep-la-rochelle" },
  { name: "La Rochelle (retour)", milestoneId: "dep-la-rochelle" },
  { name: "", milestoneId: "dep-nameless" },
  { name: "No id" },
];

describe("stopNamesFromStops", () => {
  it("maps each milestone id to its stop name, first name wins", () => {
    expect(stopNamesFromStops(stops)).toEqual({
      "dep-saint-maur-berry-indre": "Saint-Maur (Berry, Indre)",
      "dep-la-rochelle": "La Rochelle",
    });
  });

  it("is empty before the voyage has loaded", () => {
    expect(stopNamesFromStops(undefined)).toEqual({});
    expect(stopNamesFromStops(null)).toEqual({});
  });
});

describe("milestoneLabel", () => {
  const names = stopNamesFromStops(stops);

  it("shows the stop name for a known milestone", () => {
    expect(milestoneLabel(names, "dep-la-rochelle")).toBe("La Rochelle");
  });

  it("falls back to the id when the voyage does not know it", () => {
    expect(milestoneLabel(names, "leg-la-rochelle-ajaccio")).toBe("leg-la-rochelle-ajaccio");
    expect(milestoneLabel(names, "dep-nameless")).toBe("dep-nameless");
    expect(milestoneLabel(undefined, "dep-la-rochelle")).toBe("dep-la-rochelle");
    expect(milestoneLabel({}, "dep-la-rochelle")).toBe("dep-la-rochelle");
  });

  it("stays empty for a pledge with no milestone", () => {
    expect(milestoneLabel(names, "")).toBe("");
    expect(milestoneLabel(names, undefined)).toBe("");
  });
});
