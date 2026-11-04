import { describe, expect, it } from "vitest";
import { projectsNearRoute } from "./projectsNearRoute.js";

describe("projectsNearRoute", () => {
  it("ne garde que les projets proches d’une escale", () => {
    const stops = [{ name: "La Rochelle", lat: 46.15, lon: -1.15, nm: 0 }];
    const near = {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-1.16, 46.16] },
      properties: { id: "near", title: "Near" },
    };
    const far = {
      type: "Feature",
      geometry: { type: "Point", coordinates: [100, 0] },
      properties: { id: "far", title: "Far" },
    };
    const out = projectsNearRoute([near, far], stops, { maxKm: 200, limit: 50 });
    expect(out.map((f) => f.properties.id)).toEqual(["near"]);
  });
});
