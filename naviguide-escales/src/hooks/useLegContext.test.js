import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { legAtClockNow } from "./useLegContext.js";

describe("legAtClockNow", () => {
  const t0 = "2026-05-15T08:00:00Z";
  const now = "2026-10-18T08:00:00Z";
  const marks = [
    { name: "La Rochelle", nm: 0, filmNm: 0 },
    { name: "Ajaccio (Corse)", nm: 400, filmNm: 400 },
    { name: "Mata-Utu (Wallis-et-Futuna)", nm: 18000, filmNm: 18000 },
    { name: "Nouméa (Nouvelle-Calédonie)", nm: 19000, filmNm: 19000 },
  ];
  const nowHours = (Date.parse(now) - Date.parse(t0)) / 3600000;
  const clock = {
    t0,
    marks,
    vertices: [
      { tHours: 0, sailNm: 0, filmNm: 0, lat: 46.16, lon: -1.15, speedKnots: 6, bearing: 200, vehicle: "main" },
      { tHours: 100, sailNm: 400, filmNm: 400, lat: 41.92, lon: 8.73, speedKnots: 6, bearing: 180, vehicle: "main" },
      { tHours: nowHours - 48, sailNm: 18100, filmNm: 18100, lat: -13.28, lon: -176.18, speedKnots: 7.5, bearing: 210, vehicle: "main" },
      { tHours: nowHours + 200, sailNm: 19000, filmNm: 19000, lat: -22.27, lon: 166.44, speedKnots: 7.5, bearing: 210, vehicle: "main" },
    ],
  };

  it("reads the leg at clock now, not at t0 and not at the cursor", () => {
    const leg = legAtClockNow({
      clock,
      now,
      marks,
      cursor: 0,
      t0,
      speedKnots: 7.5,
    });
    assert.equal(leg.fromStop, "Mata-Utu (Wallis-et-Futuna)");
    assert.equal(leg.toStop, "Nouméa (Nouvelle-Calédonie)");
    assert.ok(leg.nmCovered > 18000);
    const atStart = legAtClockNow({
      clock,
      now: t0,
      marks,
      cursor: 18500,
      t0: now,
    });
    assert.equal(atStart.fromStop, "La Rochelle");
    assert.equal(atStart.toStop, "Ajaccio (Corse)");
    assert.notEqual(leg.fromStop, atStart.fromStop);
  });
});
