import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { bearingDeg, twaDeg, pickProfileSamples, lerpSeries, mapPool } from "./routeWindProfile.js";

describe("routeWindProfile", () => {
  it("cap et TWA", () => {
    const heading = bearingDeg({ lat: 0, lon: 0 }, { lat: 0, lon: 1 });
    assert.ok(heading > 80 && heading < 100);
    assert.equal(twaDeg(90, 90), 0);
    assert.equal(twaDeg(90, 180), 90);
    assert.equal(twaDeg(0, 350), 10);
  });

  it("samples start, stopovers and midpoints, skips the plane", () => {
    const points = [];
    for (let i = 0; i <= 20; i++) {
      points.push({
        lat: 45,
        lon: -60 + i * 0.5,
        cumNm: i * 20,
        filmCum: i * 20,
        jump: i >= 10 && i <= 12,
      });
    }
    const marks = [
      { filmNm: 0, name: "A", kind: "start" },
      { filmNm: 200, name: "B", kind: "waypoint" },
    ];
    const samples = pickProfileSamples({ points }, marks, { maxPoints: 12 });
    assert.ok(samples.length >= 3);
    assert.ok(samples.every((s) => s.kind !== "air"));
    assert.equal(samples[0].filmNm, 0);
  });

  it("interpolates a series", () => {
    const samples = [
      { filmNm: 0, tws: 10 },
      { filmNm: 100, tws: 20 },
    ];
    assert.equal(lerpSeries(samples, 50, "tws"), 15);
  });

  it("mapPool respects concurrency", async () => {
    let live = 0;
    let peak = 0;
    const out = await mapPool([1, 2, 3, 4], 2, async (n) => {
      live += 1;
      peak = Math.max(peak, live);
      await new Promise((r) => setTimeout(r, 15));
      live -= 1;
      return n * 2;
    });
    assert.deepEqual(out, [2, 4, 6, 8]);
    assert.ok(peak <= 2);
  });
});
