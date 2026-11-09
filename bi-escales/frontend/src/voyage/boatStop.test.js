import { describe, expect, it } from "vitest";
import { resolveBoatStop } from "./boatStop.js";

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

describe("resolveBoatStop", () => {
  it("picks Saint-Maur while the voyage clock is still waiting at berth", () => {
    const sample = { lat: 46.8075, lon: 1.6358, status: "waiting" };
    expect(resolveBoatStop([saintMaur, laRochelle], sample)).toEqual(saintMaur);
  });

  it("picks the nearest escale when the boat is underway", () => {
    const sample = { lat: 46.2, lon: -0.5, status: "live" };
    expect(resolveBoatStop([saintMaur, laRochelle], sample)?.milestoneId).toBe("dep-la-rochelle");
  });
});
