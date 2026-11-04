import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { LEAFLET_BUILTIN_PANES, PANES } from "./layerOrder.js";

describe("panes", () => {
  it("keeps the locked order", () => {
    assert.deepEqual(PANES.map((p) => p.name), [
      "science-wms-bathy",
      "zee-wms",
      "science-wms-substrate",
      "balisage",
      "science-wms-cables",
      "climatology-raster",
      "climatology-vector",
      "route",
      "science-tracks",
      "amp",
      "grib",
      "boat",
      "briefing-focus",
    ]);
    const focus = PANES.find((p) => p.name === "briefing-focus");
    assert.ok(focus.zIndex > PANES.find((p) => p.name === "boat").zIndex);
    assert.ok(focus.zIndex < LEAFLET_BUILTIN_PANES.tooltipPane);
    assert.equal(focus.pointerEvents, "none");
    const grib = PANES.find((p) => p.name === "grib");
    const boat = PANES.find((p) => p.name === "boat");
    assert.ok(PANES.find((p) => p.name === "route").zIndex < LEAFLET_BUILTIN_PANES.markerPane);
    assert.ok(grib.zIndex > PANES.find((p) => p.name === "amp").zIndex);
    assert.ok(grib.zIndex < LEAFLET_BUILTIN_PANES.markerPane);
    assert.ok(grib.zIndex < boat.zIndex);
    assert.equal(grib.pointerEvents, "none");
    assert.ok(boat.zIndex > LEAFLET_BUILTIN_PANES.markerPane);
    assert.ok(boat.zIndex < LEAFLET_BUILTIN_PANES.popupPane);
    assert.ok(PANES.find((p) => p.name === "science-wms-bathy").zIndex < PANES.find((p) => p.name === "route").zIndex);
    assert.ok(PANES.find((p) => p.name === "climatology-raster").zIndex < PANES.find((p) => p.name === "climatology-vector").zIndex);
    assert.ok(PANES.find((p) => p.name === "climatology-vector").zIndex < PANES.find((p) => p.name === "route").zIndex);
  });
});
