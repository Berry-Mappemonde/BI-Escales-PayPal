import { describe, expect, it } from "vitest";
import { matchVoyageStop } from "./milestoneId.js";

const stops = [
  { name: "Dzaoudzi (Mayotte)", milestoneId: "dep-dzaoudzi-mayotte", lat: -12.78, lon: 45.28 },
  { name: "Fort-de-France (Martinique)", milestoneId: "dep-fort-de-france-martinique", lat: 14.6, lon: -61.05 },
];

describe("matchVoyageStop", () => {
  it("relie le calendrier local à l'escale de la route", () => {
    expect(matchVoyageStop(stops, { name: "Mayotte", milestoneId: "dep-mayotte" })?.name).toBe("Dzaoudzi (Mayotte)");
    expect(matchVoyageStop(stops, { name: "Fort-de-France", milestoneId: "dep-fort-de-france" })?.name)
      .toBe("Fort-de-France (Martinique)");
  });
});
