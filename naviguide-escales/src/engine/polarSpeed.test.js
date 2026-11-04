import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { polarBoatSpeed, hasPolarRaw } from "./polarSpeed.js";

const raw = {
  twa_rows: [40, 120],
  tws_cols: [8, 16],
  matrix: [
    [5, 7],
    [6, 9],
  ],
};

describe("polarBoatSpeed", () => {
  it("refuse un tableau vide", () => {
    assert.equal(hasPolarRaw(null), false);
    assert.equal(polarBoatSpeed(null, 90, 12), null);
  });

  it("interpolates in the middle of the grid", () => {
    const k = polarBoatSpeed(raw, 80, 12);
    assert.ok(k > 5 && k < 9);
  });

  it("TWS 0 → 0 ; TWA 0 → 0", () => {
    assert.equal(polarBoatSpeed(raw, 90, 0), 0);
    assert.equal(polarBoatSpeed(raw, 0, 12), 0);
  });

  it("caps TWS at the grid max", () => {
    const atMax = polarBoatSpeed(raw, 120, 16);
    const above = polarBoatSpeed(raw, 120, 40);
    assert.equal(atMax, above);
    assert.equal(atMax, 9);
  });
});
