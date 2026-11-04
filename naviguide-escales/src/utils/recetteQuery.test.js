import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { recetteClimoFlags, recetteMapView, recetteMonth } from "./recetteQuery.js";

describe("recetteQuery", () => {
  it("reads climo=cyclones and map=28,180,3", () => {
    const flags = recetteClimoFlags("?climo=cyclones");
    assert.equal(flags.cyclones, true);
    assert.equal(flags.wind, false);
    const view = recetteMapView("?map=28,180,3");
    assert.deepEqual(view, { lat: 28, lon: 180, z: 3 });
    assert.equal(recetteMonth("?month=9"), 9);
  });
});
