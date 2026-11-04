import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { COASTAL_CUTOFF_NM, gebcoLookup } from "./gebco.js";

const GRID = { sample: () => -4200 };

describe("gebcoLookup", () => {
  it("without a grid: honest null", () => {
    assert.equal(gebcoLookup(0, -30), null);
  });

  it("near the coast (< 20 M): null even with a grid", () => {
    assert.equal(gebcoLookup(46.15, -1.16, { grid: GRID, distToShoreNm: 5 }), null);
    assert.ok(COASTAL_CUTOFF_NM === 20);
  });

  it("open Atlantic + grid: a depth", () => {
    assert.equal(gebcoLookup(35, -40, { grid: GRID, distToShoreNm: 800 }), -4200);
  });
});
