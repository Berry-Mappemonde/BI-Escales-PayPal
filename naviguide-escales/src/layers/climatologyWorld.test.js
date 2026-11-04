import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  climoPointLngs,
  cycloneLatLngCopies,
  groupCycloneFeatures,
  unwrapCycloneCoords,
} from "./climatologyWorld.js";

describe("climatologyWorld antimeridian", () => {
  it("triples a Pacific rose so the +360 copy of the map is not empty", () => {
    assert.deepEqual(climoPointLngs(166.4), [166.4, 526.4, -193.6]);
    assert.deepEqual(climoPointLngs(-179.2), [-179.2, 180.8, -539.2]);
  });

  it("unwraps 179 → −179 into 179 → 181 (never the long way)", () => {
    const u = unwrapCycloneCoords([
      [170, -15],
      [179, -16],
      [-179, -17],
      [-170, -18],
    ]);
    assert.deepEqual(u, [
      [170, -15],
      [179, -16],
      [181, -17],
      [190, -18],
    ]);
  });

  it("paints one polyline per world copy, crossing 180° without a cut", () => {
    const copies = cycloneLatLngCopies([
      [170, -15],
      [179, -16],
      [-179, -17],
      [-170, -18],
    ]);
    assert.ok(copies.length >= 3);
    const byFirst = new Map(copies.map((part) => [part[0][1], part]));
    assert.deepEqual(byFirst.get(170).map((ll) => ll[1]), [170, 179, 181, 190]);
    assert.deepEqual(byFirst.get(530).map((ll) => ll[1]), [530, 539, 541, 550]);
    assert.deepEqual(byFirst.get(-190).map((ll) => ll[1]), [-190, -181, -179, -170]);
    for (const part of copies) {
      assert.ok(part.length >= 2);
      for (let i = 1; i < part.length; i++) {
        assert.ok(Math.abs(part[i][1] - part[i - 1][1]) <= 180);
      }
    }
  });

  it("rejoins backend-split parts of the same sid then unwraps to one line", () => {
    const groups = groupCycloneFeatures([
      { properties: { sid: "A", name: "TEST" }, geometry: { coordinates: [[170, -15], [179, -16]] } },
      { properties: { sid: "A" }, geometry: { coordinates: [[-179, -17], [-170, -18]] } },
    ]);
    assert.equal(groups.length, 1);
    assert.deepEqual(unwrapCycloneCoords(groups[0].coords), [
      [170, -15],
      [179, -16],
      [181, -17],
      [190, -18],
    ]);
  });
});
