import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { normalizeMarkerBearing } from "./markerRotation.js";

describe("normalizeMarkerBearing", () => {
  it("normalise un cap dans le domaine CSS 0–360", () => {
    assert.equal(normalizeMarkerBearing(-15), 345);
    assert.equal(normalizeMarkerBearing(725), 5);
    assert.equal(normalizeMarkerBearing("invalid"), 0);
  });
});
