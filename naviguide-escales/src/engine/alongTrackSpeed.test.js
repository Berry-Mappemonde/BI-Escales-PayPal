import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { alongTrackSpeed } from "./alongTrackSpeed.js";

const LEOPARD_RAW = {
  twa_rows: [52, 60, 75, 90, 110, 135, 150],
  tws_cols: [8, 10, 12, 16, 20],
  matrix: [
    [5.2, 6.1, 6.8, 7.4, 7.6],
    [5.8, 6.8, 7.5, 8.2, 8.4],
    [6.4, 7.4, 8.2, 8.9, 9.1],
    [6.6, 7.6, 8.4, 9.2, 9.4],
    [6.3, 7.3, 8.1, 8.8, 9.0],
    [5.5, 6.5, 7.2, 8.0, 8.3],
    [4.8, 5.6, 6.3, 7.1, 7.4],
  ],
};

describe("alongTrackSpeed", () => {
  it("kind climatology, no polar: no crash", () => {
    const s = alongTrackSpeed({ lat: 15, lon: -25, bearing: 250, month: 6, polarRaw: null });
    assert.equal(s.kind, "climatology");
    assert.ok(s.speedKnots >= 4);
    assert.ok(s.windKnots > 0);
  });

  it("trades: March faster than July (same heading)", () => {
    const args = { lat: 15, lon: -25, bearing: 250, polarRaw: null };
    const mar = alongTrackSpeed({ ...args, month: 3 });
    const jul = alongTrackSpeed({ ...args, month: 7 });
    assert.ok(mar.speedKnots > jul.speedKnots);
  });

  it("Leopard 46 raw: finite knots, TWA filled", () => {
    const s = alongTrackSpeed({
      lat: 15,
      lon: -25,
      bearing: 250,
      month: 6,
      polarRaw: LEOPARD_RAW,
    });
    assert.equal(s.kind, "climatology");
    assert.ok(Number.isFinite(s.speedKnots) && s.speedKnots > 0);
    assert.ok(s.twa != null && s.twa >= 0 && s.twa <= 180);
  });

  it("atlas wind: kind stays climatology, Hs and current travel with the pack", () => {
    const s = alongTrackSpeed({
      lat: 15,
      lon: -25,
      bearing: 250,
      month: 6,
      polarRaw: null,
      wind: {
        speedKnots: 16.2,
        dirFromDeg: 55,
        kind: "climatology",
        source: "atlas",
        period: "1980-2020",
        doi: { wind: "10.48670/moi-00183" },
        hsP50: 1.4,
        hsP90: 2.8,
        currentKn: 0.4,
      },
    });
    assert.equal(s.kind, "climatology");
    assert.equal(s.source, "atlas");
    assert.equal(s.hsP90, 2.8);
    assert.equal(s.currentKn, 0.4);
    assert.equal(s.period, "1980-2020");
  });

  it("wind provided: kind forecast and named model", () => {
    const s = alongTrackSpeed({
      lat: 15,
      lon: -25,
      bearing: 250,
      month: 6,
      polarRaw: null,
      wind: {
        speedKnots: 22,
        dirFromDeg: 90,
        kind: "forecast",
        model: "GFS 0.25° (Open-Meteo)",
      },
    });
    assert.equal(s.kind, "forecast");
    assert.equal(s.model, "GFS 0.25° (Open-Meteo)");
    assert.ok(s.speedKnots > 0);
  });
});
