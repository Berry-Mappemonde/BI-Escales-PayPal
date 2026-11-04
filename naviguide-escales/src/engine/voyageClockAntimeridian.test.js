import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { lerpLon, sampleClockAtHours } from "./voyageClock.js";
import { wrapLon } from "../utils/geo.js";

const vertex = (lon, tHours, filmNm) => ({
  filmNm, sailNm: filmNm, lat: -20, lon, bearing: 270, tHours,
  iso: null, speedKnots: 8, windKnots: 15, twa: 120, month: 10,
  vehicle: "main", kind: "climatology", regime: "climatology", seaHours: tHours,
});

describe("horloge — antiméridien (18/10, marqueur en Australie)", () => {
  it("lerpLon suit le plus court arc", () => {
    const mid = lerpLon(-180, 179.85, 43 / 60);
    assert.ok(Math.abs(Math.abs(wrapLon(mid)) - 180) < 0.2, String(mid));
    assert.equal(lerpLon(-185, -193, 0.5), -189);
  });

  it("sampleClockAtHours ne traverse pas le globe entre -180 et 179.85", () => {
    const clock = {
      t0: "2026-10-18T06:34:06Z",
      vertices: [vertex(-180, 0, 0), vertex(179.8506921644703, 1, 8.7)],
      marks: [],
    };
    for (const t of [0.1, 0.5, 43 / 60, 0.9]) {
      const s = sampleClockAtHours(clock, t);
      assert.ok(Math.abs(Math.abs(wrapLon(s.lon)) - 180) < 0.2, `${t}: ${s.lon}`);
    }
  });
});
