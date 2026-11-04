import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  atlasLayerUrl,
  atlasOrZone,
  atlasPointUrl,
  atlasTileUrl,
  cellKey,
  civilMonth,
  compactAtlasFields,
  hasAtlasBlocks,
  visibleClimoTiles,
  windFromAtlasPoint,
} from "./atlasPoint.js";

const ATLANTIC_POINT = {
  kind: "climatology",
  month: 6,
  period: "1980-2020",
  doi: { wind: "10.48670/moi-00183" },
  periods: { wind: "1994-2020", wave: "1993-2019", current: "1993-2016" },
  wind_atlas: {
    most_likely: { speed_knots: 16.2, dir_deg: 55 },
    vector_mean: { speed_knots: 14.1, dir_deg: 60 },
  },
  wave: { hs_p50_m: 1.4, hs_p90_m: 2.8, stat: "p50_p90" },
  current: { speed_knots: 0.4, direction_to_deg: 270 },
  cyclone: { nearby: 1, tracks_in_month: 12, crossings_if_leg: { count: 2 } },
};

describe("atlasPoint", () => {
  it("keeps kind climatology and never invents a forecast", () => {
    const w = windFromAtlasPoint(ATLANTIC_POINT);
    assert.equal(w.kind, "climatology");
    assert.equal(w.source, "atlas");
    assert.equal(w.speedKnots, 16.2);
    assert.equal(w.dirFromDeg, 55);
    assert.equal(w.hsP50, 1.4);
    assert.equal(w.hsP90, 2.8);
    assert.equal(w.currentKn, 0.4);
    assert.equal(w.period, "1980-2020");
    assert.equal(w.doi.wind, "10.48670/moi-00183");
    assert.equal(w.crossings.count, 2);
    assert.equal(w.point, ATLANTIC_POINT);
  });

  it("falls back to the zone only when the atlas payload is dead", () => {
    const zone = atlasOrZone(15, -25, 6, null);
    assert.equal(zone.kind, "climatology");
    assert.equal(zone.source, "zone_fallback");
    assert.ok(zone.speedKnots > 0);
    assert.equal(windFromAtlasPoint({ kind: "forecast" }), null);
    assert.equal(windFromAtlasPoint({ kind: "climatology" }), null);
  });

  it("builds /bi climatology URLs with month and dest", () => {
    const point = atlasPointUrl({ lat: 15, lon: -25, month: 6, destLat: 14.6, destLon: -61 });
    assert.match(point, /^\/bi\/climatology\/point\?/);
    assert.match(point, /month=6/);
    assert.match(point, /dest_lat=14\.6/);
    assert.match(atlasPointUrl({ lat: 15, lon: 186, month: 9 }), /lon=-174/);
    assert.equal(atlasLayerUrl("wave", 6, { stat: "p90", spacing_deg: "4" }).includes("stat=p90"), true);
    assert.match(
      atlasLayerUrl("wind", 5, { spacing_deg: "4" }),
      /\/climatology\/wind\.geojson\?.*month=5.*spacing_deg=4|\/climatology\/wind\.geojson\?.*spacing_deg=4.*month=5/,
    );
    assert.equal(
      atlasTileUrl("wind", 6, 4, 8, 5),
      "/bi/climatology/wind/tiles/4/8/5.json?month=6",
    );
    assert.match(atlasTileUrl("wave", 9, 3, 2, 1, { stat: "p90" }), /stat=p90/);
    assert.equal(cellKey(15.1, -25.1, 6), cellKey(15.2, -25.2, 6));
    assert.equal(civilMonth("2026-07-15T08:00:00.000Z"), 7);
  });

  it("enumerates visible tiles and wraps x across the antimeridian", () => {
    const europe = visibleClimoTiles({ west: -10, south: 35, east: 20, north: 55 }, 4, { margin: 0 });
    assert.ok(europe.length >= 1);
    assert.ok(europe.every((t) => t.z === 4 && t.x >= 0 && t.x < 16 && t.y >= 0 && t.y < 16));

    const wrap = visibleClimoTiles({ west: 170, south: -10, east: -170, north: 10 }, 3, { margin: 1 });
    const xs = [...new Set(wrap.map((t) => t.x))].sort((a, b) => a - b);
    assert.ok(wrap.every((t) => t.z === 3));
    assert.ok(xs.includes(0), `expected x=0 among ${xs}`);
    assert.ok(xs.includes(7), `expected x=7 among ${xs}`);
    assert.ok(xs[0] < xs[xs.length - 1] || xs.includes(0));
  });

  it("compacts fields for the clock without dropping kind", () => {
    const compact = compactAtlasFields(windFromAtlasPoint(ATLANTIC_POINT));
    assert.equal(compact.source, "atlas");
    assert.equal(compact.hsP90, 2.8);
    assert.ok(!("point" in compact));
    assert.equal(hasAtlasBlocks(ATLANTIC_POINT), true);
    assert.equal(hasAtlasBlocks({ kind: "climatology" }), false);
  });
});
