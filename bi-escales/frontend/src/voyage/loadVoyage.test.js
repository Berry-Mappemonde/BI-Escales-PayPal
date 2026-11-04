import { describe, expect, it } from "vitest";
import { PRODUCTION_T0_ISO } from "./departureT0.js";
import { voyageFromRoute, sampleAt } from "./loadVoyage.js";

describe("voyageFromRoute", () => {
  it("calcule des milles cumulés et l'horloge", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { from: "La Rochelle", to: "Ajaccio (Corse)", type: "maritime" },
          geometry: { type: "LineString", coordinates: [[-1.167, 46.1541], [8.7386, 41.9192]] },
        },
        {
          type: "Feature",
          properties: { name: "La Rochelle", point_type: "escale" },
          geometry: { type: "Point", coordinates: [-1.167, 46.1541] },
        },
      ],
    };
    const voyage = voyageFromRoute(fc, PRODUCTION_T0_ISO);
    expect(voyage.flat.totalNm).toBeGreaterThan(100);
    expect(voyage.clock.t0).toBe(PRODUCTION_T0_ISO);
    expect(voyage.stops[0].milestoneId).toBe("dep-la-rochelle");
    const before = sampleAt(voyage.clock, new Date("2026-11-01T08:00:00.000Z"));
    expect(before.status).toBe("waiting");
    expect(before.sailNm).toBe(0);
  });
});
