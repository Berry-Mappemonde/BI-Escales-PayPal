import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { seaHours, seaDays, formatSeaTime, formatSeaClock, clockTickLabels } from "./seaTime.js";

describe("seaTime", () => {
  it("7 kt : 168 nm = 24 h = 1 jour", () => {
    assert.equal(seaHours(168, 7), 24);
    assert.equal(seaDays(168, 7), 1);
  });

  it("Berry 39 000 nm at 7 kt ≈ 232 days", () => {
    const days = seaDays(39_000, 7);
    assert.ok(days > 231 && days < 233);
    assert.equal(formatSeaClock(39_000, 7, { compact: true }), "232 j");
  });

  it("invalid speed falls back to 7 kt", () => {
    assert.equal(seaHours(7, 0), 1);
    assert.equal(seaHours(7, -3), 1);
  });

  it("formate heures et jours", () => {
    assert.equal(formatSeaTime(4.2), "4.2 h");
    assert.equal(formatSeaTime(30), "1 j 6 h");
    assert.equal(formatSeaTime(48), "2 j");
    assert.equal(formatSeaTime(47.7), "2 j");
  });

  it("D0 / midpoint / D232 marks for Berry", () => {
    const ticks = clockTickLabels({
      playheadTotal: 39_000,
      sailTotalNm: 39_000,
      knots: 7,
      scale: "days",
    });
    assert.equal(ticks[0].label, "J0");
    assert.equal(ticks[2].label, "J232");
  });

  it("nm et jours ensemble, plus de bascule", () => {
    const ticks = clockTickLabels({
      playheadTotal: 39_000,
      sailTotalNm: 39_000,
      knots: 7,
      scale: "both",
    });
    assert.match(ticks[0].label, /0 nm · j0/);
    assert.match(ticks[2].label, /39[,.\s ]?000 nm · j232/);
  });
});
