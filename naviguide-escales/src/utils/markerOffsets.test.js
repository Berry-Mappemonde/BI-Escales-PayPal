import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  computeMarkerOffsets,
  capOffset,
  hasFlag,
  MAX_OFFSET,
  FLAG_W,
  FLAG_H,
  rectHitsRoute,
  offsetToIconAnchor,
  isOffsetStillClear,
} from "./markerOffsets.js";

const identityProject = (lon, lat) => ({ x: lon, y: lat });

describe("hasFlag / capOffset", () => {
  it("treats an empty string as an intermediate point", () => {
    assert.equal(hasFlag({ flag: "" }), false);
    assert.equal(hasFlag({ flag: "/flags/fr.png" }), true);
    assert.equal(hasFlag({ flags: ["kanak", "france"] }), true);
    assert.equal(hasFlag({ flags: [] }), false);
  });

  it("plafonne un offset trop long", () => {
    const [ox, oy] = capOffset(0, -400);
    assert.ok(Math.hypot(ox, oy) <= MAX_OFFSET + 1e-6);
    assert.equal(ox, 0);
    assert.ok(oy < 0);
  });
});

describe("computeMarkerOffsets", () => {
  it("leaves intermediate points at [0, 0]", () => {
    const points = [
      { lon: 0, lat: 0, flag: "" },
      { lon: 10, lat: 10, flag: "" },
    ];
    const offsets = computeMarkerOffsets(points, identityProject);
    assert.deepEqual(offsets[0], [0, 0]);
    assert.deepEqual(offsets[1], [0, 0]);
  });

  it("never lets a flag go beyond MAX_OFFSET", () => {
    const points = [];
    for (let i = 0; i < 12; i++) {
      points.push({ lon: 100 + i * 2, lat: 100 + i * 2, flag: "x" });
    }
    const offsets = computeMarkerOffsets(points, identityProject);
    for (const [ox, oy] of offsets) {
      assert.ok(Math.hypot(ox, oy) <= MAX_OFFSET + 1e-6, `${ox},${oy}`);
    }
  });

  it("separates two flags that are too close", () => {
    const points = [
      { lon: 50, lat: 50, flag: "a" },
      { lon: 52, lat: 50, flag: "b" },
    ];
    const offsets = computeMarkerOffsets(points, identityProject);
    const ax = 50 + offsets[0][0];
    const ay = 50 + offsets[0][1];
    const bx = 52 + offsets[1][0];
    const by = 50 + offsets[1][1];
    const dist = Math.hypot(bx - ax, by - ay);
    assert.ok(dist >= 20, `drapeaux trop proches: ${dist}`);
  });

  it("avoids placing the flag rectangle on the route", () => {
    const points = [{ lon: 0, lat: 0, flag: "a" }];
    // Route horizontale qui passe par l'ancre — un offset (0,0) recouperait
    const routeSegs = [{ ax: -80, ay: 0, bx: 80, by: 0 }];
    const [ox, oy] = computeMarkerOffsets(points, identityProject, routeSegs)[0];
    const rect = {
      x: ox - FLAG_W / 2,
      y: oy - FLAG_H,
      w: FLAG_W,
      h: FLAG_H,
    };
    assert.equal(rectHitsRoute(rect, routeSegs, 2), false);
  });

  it("exprime le décalage dans l'ancre (planté sur le latlng)", () => {
    assert.deepEqual(offsetToIconAnchor([18, 12], [0, -36]), [18, 48]);
    assert.deepEqual(offsetToIconAnchor([11, 12], [8, -20]), [3, 32]);
  });

  it("réutilise l'offset précédent tant que rien ne se chevauche", () => {
    const points = [
      { lon: 0, lat: 0, flag: "a" },
      { lon: 200, lat: 0, flag: "b" },
    ];
    const first = computeMarkerOffsets(points, identityProject);
    const zoomed = (lon, lat) => ({ x: lon * 3, y: lat * 3 });
    const second = computeMarkerOffsets(points, zoomed, [], first);
    assert.deepEqual(second, first);
    assert.equal(isOffsetStillClear({ x: 0, y: 0 }, first[0], []), true);
  });

  it("recalcule si l'offset précédent chevauche un autre drapeau", () => {
    const points = [
      { lon: 0, lat: 0, flag: "a" },
      { lon: 2, lat: 0, flag: "b" },
    ];
    const next = computeMarkerOffsets(points, identityProject, [], [[0, 0], [0, 0]]);
    const ax = 0 + next[0][0];
    const ay = 0 + next[0][1];
    const bx = 2 + next[1][0];
    const by = 0 + next[1][1];
    assert.ok(Math.hypot(bx - ax, by - ay) >= 20, "drapeaux toujours séparés après recalcul");
  });
});
