import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { climatologyLayerState, gribWindLayerState, productLayerState, weatherPipelineEnabled } from "./useWeatherPipeline.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (name) => readFileSync(join(here, name), "utf8");

describe("useWeatherPipeline", () => {
  it("is on unless the variable is 0 or off", () => {
    assert.equal(weatherPipelineEnabled({}), true);
    assert.equal(weatherPipelineEnabled({ VITE_NAVIGUIDE_WEATHER_PIPELINE: "" }), true);
    assert.equal(weatherPipelineEnabled({ NAVIGUIDE_WEATHER_PIPELINE: "off" }), false);
    assert.equal(weatherPipelineEnabled({ VITE_NAVIGUIDE_WEATHER_PIPELINE: "0" }), false);
    assert.equal(weatherPipelineEnabled({ VITE_NAVIGUIDE_WEATHER_PIPELINE: "1" }), true);
    assert.equal(weatherPipelineEnabled({ NAVIGUIDE_WEATHER_PIPELINE: "on" }), true);
  });

  it("exposes per-layer state and the map does not wait", () => {
    assert.equal(gribWindLayerState(null, false), null);
    assert.equal(gribWindLayerState({ status: "ready" }, false), null);
    assert.equal(gribWindLayerState(null, true), "pending");
    assert.equal(gribWindLayerState({ status: "ready" }, true), "ready");
    assert.equal(gribWindLayerState({ status: "pending", refreshing: true }, true), "pending");
    assert.equal(gribWindLayerState({ status: "absent" }, true), "unavailable");
    assert.equal(
      gribWindLayerState({ status: "pending", layers: { gribWind: { status: "unavailable" } } }, true),
      "unavailable",
    );
    const hook = read("useWeatherPipeline.js");
    const scene = read("../map/MapScene.jsx");
    assert.match(hook, /blocksMap: false/);
    assert.match(scene, /useWeatherPipeline\(/);
    assert.match(scene, /setMapReady\(1\)/);
    assert.match(scene, /maritimeLayers\.showGrib && scene\.isSuivre/);
    assert.doesNotMatch(scene, /await /);
    assert.equal(productLayerState(null, false), null);
    assert.equal(productLayerState({ hs: 1.1 }, false), null);
    assert.equal(productLayerState(null, true), "pending");
    assert.equal(productLayerState({ status: "ready", hs: 1.1 }, true), "ready");
    assert.equal(productLayerState({ status: "pending", refreshing: true }, true), "pending");
    assert.equal(productLayerState({ status: "error", hs: 1.1 }, true), "unavailable");
    assert.equal(productLayerState({ status: "unavailable" }, true), "unavailable");
    assert.equal(climatologyLayerState({ loading: true, counts: null, error: null }, false), null);
    assert.equal(climatologyLayerState({ loading: true, counts: null, error: null }, true), "pending");
    assert.equal(climatologyLayerState({ loading: false, counts: { wind: 4 }, error: null }, true), "ready");
    assert.equal(climatologyLayerState({ loading: false, counts: null, error: "down" }, true), "unavailable");
    assert.match(scene, /climatology: climoLayer/);
    assert.match(hook, /blocksMap: false/);
  });
});
