import { describe, expect, it } from "vitest";
import { dedupeStopsByMilestone } from "./stopsForMap.js";

describe("dedupeStopsByMilestone", () => {
  it("keeps a single La Rochelle marker when the route lists it twice", () => {
    const saintMaur = {
      name: "Saint-Maur (Berry, Indre)",
      lat: 46.8075,
      lon: 1.6358,
      milestoneId: "dep-saint-maur-berry-indre",
    };
    const laRochelle = {
      name: "La Rochelle",
      lat: 46.1541,
      lon: -1.167,
      milestoneId: "dep-la-rochelle",
    };
    const out = dedupeStopsByMilestone([saintMaur, laRochelle, { ...laRochelle }]);
    expect(out).toHaveLength(2);
    expect(out.map((row) => row.milestoneId)).toEqual([
      "dep-saint-maur-berry-indre",
      "dep-la-rochelle",
    ]);
  });
});
