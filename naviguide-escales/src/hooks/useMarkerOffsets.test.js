import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  CAMERA_IDLE_MS,
  ZOOM_IDLE_MS,
  flagWorldLngsForView,
  markerOffsetDelay,
  shouldComputeOffsetsOnEvent,
  viewTouchesAntimeridian,
} from "./useMarkerOffsets.js";

describe("offsets pendant le zoom", () => {
  it("ne recalcule pas pendant zoomanim ; zoomend attend 250 ms", () => {
    assert.equal(shouldComputeOffsetsOnEvent("zoomanim"), false);
    assert.equal(shouldComputeOffsetsOnEvent("zoomend"), true);
    assert.equal(shouldComputeOffsetsOnEvent("moveend"), true);
    assert.equal(ZOOM_IDLE_MS, 250);
    assert.equal(markerOffsetDelay(false, "zoom"), 250);
    assert.equal(markerOffsetDelay(true, "zoom"), 250);
    assert.equal(markerOffsetDelay(false, "move"), 120);
    assert.equal(markerOffsetDelay(true, "move"), CAMERA_IDLE_MS);
  });
});

describe("copies-monde des drapeaux", () => {
  it("Atlantique (vue loin de ±180°) : une seule copie", () => {
    assert.equal(viewTouchesAntimeridian(-80, 10), false);
    const lngs = flagWorldLngsForView(-1.5, -20, -80, 10);
    assert.equal(lngs.length, 1);
  });

  it("vue qui touche ±180° : copies monde", () => {
    assert.equal(viewTouchesAntimeridian(160, 190), true);
    assert.equal(viewTouchesAntimeridian(170, 175), true);
    assert.ok(flagWorldLngsForView(179, 170, 160, 190).length > 1);
  });
});
