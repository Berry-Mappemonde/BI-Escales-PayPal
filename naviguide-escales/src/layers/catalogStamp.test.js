import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { catalogMayTakeClick, featureStamp, releaseCatalogPick } from "./catalogStamp.js";

const pt = { type: "Feature", properties: { naviguideCatalogId: "marinas:1" }, geometry: { type: "Point", coordinates: [-1.1, 46.1] } };

describe("catalog feature stamp", () => {
  it("a kept point is drawn again when the zoom step changes (its radius follows)", () => {
    assert.equal(featureStamp(pt, 6), featureStamp(pt, 6.2));
    assert.notEqual(featureStamp(pt, 6), featureStamp(pt, 9));
  });

  it("a shape is known by id, vertex count and extent, not by its JSON", () => {
    const ring = Array.from({ length: 2000 }, (_, i) => [Math.cos(i / 318) * 2, Math.sin(i / 318) * 2]);
    const poly = { type: "Feature", properties: { naviguideCatalogId: "amp:1" }, geometry: { type: "Polygon", coordinates: [ring] } };
    const stamp = featureStamp(poly, 5);
    assert.ok(stamp.length < 120, stamp);
    assert.match(stamp, /^amp:1\|Polygon\|2000\|/);
    const moved = { ...poly, geometry: { type: "Polygon", coordinates: [ring.map(([x, y]) => [x + 1, y])] } };
    assert.notEqual(featureStamp(moved, 5), stamp);
    const fewer = { ...poly, geometry: { type: "Polygon", coordinates: [ring.slice(0, 1000)] } };
    assert.notEqual(featureStamp(fewer, 5), stamp);
    assert.equal(featureStamp(poly, 9), stamp);
  });
});

describe("catalog click pick", () => {
  const el = (selectors) => ({ closest: (q) => (q.split(",").map((s) => s.trim()).some((s) => selectors.includes(s)) ? {} : null) });

  it("leaves the briefing highlight, markers, popups and other vector layers their click", () => {
    assert.equal(catalogMayTakeClick(el([".leaflet-briefing-focus-pane"])), false);
    assert.equal(catalogMayTakeClick(el([".leaflet-marker-icon"])), false);
    assert.equal(catalogMayTakeClick(el([".leaflet-popup"])), false);
    assert.equal(catalogMayTakeClick(el(["path.leaflet-interactive"])), false);
  });

  it("takes a click on the map or on a catalog canvas", () => {
    assert.equal(catalogMayTakeClick(el([])), true);
    assert.equal(catalogMayTakeClick(null), false);
  });
});

describe("catalog click listener", () => {
  it("leaves with the last catalog layer of its map, not before", () => {
    const removed = [];
    const handler = () => {};
    const map = { _biCatalogPick: handler, getContainer: () => ({ removeEventListener: (type, fn, capture) => removed.push([type, fn, capture]) }) };
    const other = { map };
    assert.equal(releaseCatalogPick(map, new Set([other])), false);
    assert.equal(map._biCatalogPick, handler);
    assert.equal(releaseCatalogPick(map, new Set([{ map: {} }])), true);
    assert.deepEqual(removed, [["click", handler, true]]);
    assert.equal(map._biCatalogPick, null);
    assert.equal(releaseCatalogPick(map, new Set()), false);
  });
});
