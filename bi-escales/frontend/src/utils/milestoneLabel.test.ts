import { describe, expect, it, vi } from "vitest";
import { milestoneLabel, stopNamesFromStops } from "./milestoneLabel";

const stops = [
  { name: "Saint-Maur (Berry, Indre)", milestoneId: "dep-saint-maur-berry-indre" },
  { name: "Ajaccio (Corse)", milestoneId: "dep-ajaccio-corse" },
  { name: "La Rochelle", milestoneId: "dep-la-rochelle" },
  { name: "La Rochelle (retour)", milestoneId: "dep-la-rochelle" },
  { name: "", milestoneId: "dep-nameless" },
  { name: "No id" },
];

describe("stopNamesFromStops", () => {
  it("maps each milestone id to its stop name, first name wins", () => {
    expect(stopNamesFromStops(stops)).toEqual({
      "dep-saint-maur-berry-indre": "Saint-Maur (Berry, Indre)",
      "dep-ajaccio-corse": "Ajaccio (Corse)",
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

  describe("cabin legs", () => {
    const leg = "leg-la-rochelle-to-ajaccio-corse";

    it("names both ends of a leg", () => {
      expect(milestoneLabel(names, leg)).toBe("Cabin: La Rochelle → Ajaccio (Corse)");
      expect(milestoneLabel(names, "leg-saint-maur-berry-indre-to-la-rochelle")).toBe(
        "Cabin: Saint-Maur (Berry, Indre) → La Rochelle",
      );
    });

    it("is worded by the translator it is given", () => {
      const t = vi.fn((key: string, values: { from: string; to: string }) => `${key}|${values.from}|${values.to}`);
      expect(milestoneLabel(names, leg, t)).toBe("treasurer.cabinLeg|La Rochelle|Ajaccio (Corse)");
      expect(t).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["the destination is unknown", "leg-la-rochelle-to-atlantis"],
      ["the origin is unknown", "leg-atlantis-to-la-rochelle"],
      ["both ends are unknown", "leg-atlantis-to-el-dorado"],
      ["there is no separator", "leg-la-rochelle-ajaccio-corse"],
      ["an end is missing", "leg-la-rochelle-to-"],
      ["the origin is missing", "leg--to-la-rochelle"],
      ["it is only the prefix", "leg-"],
    ])("keeps the raw id when %s", (_case, id) => {
      const t = vi.fn(() => "never");
      expect(milestoneLabel(names, id, t)).toBe(id);
      expect(t).not.toHaveBeenCalled();
    });

    it("keeps the raw id when no stop names are known", () => {
      expect(milestoneLabel(undefined, leg)).toBe(leg);
      expect(milestoneLabel({}, leg)).toBe(leg);
    });

    it("splits on the separator that leaves two known stops", () => {
      const tricky = { "dep-porto-to-go": "Porto To Go", "dep-la-rochelle": "La Rochelle" };
      expect(milestoneLabel(tricky, "leg-porto-to-go-to-la-rochelle")).toBe("Cabin: Porto To Go → La Rochelle");
      expect(milestoneLabel(tricky, "leg-la-rochelle-to-porto-to-go")).toBe("Cabin: La Rochelle → Porto To Go");
    });

    it("does not read a stop id as a leg", () => {
      expect(milestoneLabel(names, "dep-la-rochelle-to-ajaccio-corse")).toBe("dep-la-rochelle-to-ajaccio-corse");
    });
  });
});
