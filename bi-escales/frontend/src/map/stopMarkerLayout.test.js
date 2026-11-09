import { describe, expect, it } from "vitest";
import { computeMarkerOffsets } from "../../../../naviguide-escales/src/utils/markerOffsets.js";
import { boatMarkerAnchorOffset } from "./stopMarkerLayout.js";

describe("stopMarkerLayout", () => {
  it("spreads coincident screen positions so each flag keeps its own hit target", () => {
    const stops = [
      { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: true, flags: ["x.png"] },
      { name: "La Rochelle", lat: 46.1541, lon: -1.167, flag: true, flags: ["y.png"] },
    ];
    const project = () => ({ x: 240, y: 180 });
    const offsets = computeMarkerOffsets(stops, project, []);
    expect(offsets[0]).not.toEqual(offsets[1]);
  });

  it("offsets the catamaran away from a stop sharing its coordinates", () => {
    const stops = [
      { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: true, flags: ["x.png"] },
    ];
    const boat = { lat: 46.8075, lon: 1.6358 };
    const offset = boatMarkerAnchorOffset(boat, stops, [[0, -36]]);
    expect(offset).toEqual([36, 28]);
  });
});
