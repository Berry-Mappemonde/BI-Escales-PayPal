import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  activeRouteSegments,
  activeRouteStops,
  buildRouteTargets,
  routeStartPos,
  stopsFromCustomRoute,
} from "./activeRoute.js";

const customFc = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "Point 1" },
      geometry: { type: "Point", coordinates: [-17.32, 48.15] },
    },
    {
      type: "Feature",
      properties: { name: "Point 2" },
      geometry: { type: "Point", coordinates: [-21.27, 31.97] },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-17.32, 48.15],
          [-21.27, 31.97],
        ],
      },
    },
  ],
};

describe("stopsFromCustomRoute", () => {
  it("marque chaque waypoint comme escale", () => {
    const stops = stopsFromCustomRoute(customFc);
    assert.equal(stops.length, 2);
    assert.equal(stops[0].name, "Point 1");
    assert.equal(stops[0].flag, true);
    assert.equal(stops[1].lat, 31.97);
  });
});

describe("buildRouteTargets", () => {
  it("starts from the first polyline point, not La Rochelle", () => {
    const segs = activeRouteSegments(customFc, []);
    const targets = buildRouteTargets(segs);
    assert.ok(targets.length >= 3);
    assert.equal(targets[0].lat, 48.15);
    assert.equal(targets[0].lon, -17.32);
    const last = targets[targets.length - 1];
    assert.equal(last.lat, 31.97);
    assert.equal(last.lon, -21.27);
    assert.ok(Math.abs(targets[0].lat - 46.1541) > 1);
  });

  it("falls back to stops if there is no LineString", () => {
    const stops = [{ lat: 10, lon: 20 }, { lat: 11, lon: 21 }];
    const targets = buildRouteTargets([], stops);
    assert.deepEqual(targets, [
      { lat: 10, lon: 20 },
      { lat: 11, lon: 21 },
    ]);
  });
});

describe("activeRouteStops / start", () => {
  it("uses the custom route when it is displayed", () => {
    const berry = [{ name: "La Rochelle", lat: 46.15, lon: -1.16, flag: "fr" }];
    const stops = activeRouteStops(customFc, berry);
    assert.equal(stops[0].name, "Point 1");
    const start = routeStartPos(buildRouteTargets(activeRouteSegments(customFc, [])));
    assert.equal(start.lat, 48.15);
  });

  it("keeps Berry without a custom route", () => {
    const berry = [{ name: "La Rochelle", lat: 46.15, lon: -1.16, flag: "fr" }];
    assert.equal(activeRouteStops(null, berry)[0].name, "La Rochelle");
  });
});
