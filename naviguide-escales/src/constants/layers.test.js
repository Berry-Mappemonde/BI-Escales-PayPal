import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ALL_LAYER_CONFIG, DEFAULT_SHOW_GRIB, DEFAULT_SHOW_ZEE } from "./layers.js";

describe("ALL_LAYER_CONFIG", () => {
  it("GRIB2 en premier, juste avant ZEE", () => {
    const keys = ALL_LAYER_CONFIG.map((c) => c.key);
    assert.deepEqual(keys, [
      "grib2", "zee", "wpi", "balisage", "projects", "marinas",
      "capitaineries", "poe", "amp",
      "sextant", "argo", "odatis", "edmed", "csr",
      "bathymetry", "fonds", "cables",
      "climo-wind", "climo-wave", "climo-current", "climo-cyclones",
    ]);
    assert.equal(keys.includes("science"), false);
    assert.equal(keys[0], "grib2");
    assert.equal(keys[1], "zee");
  });

  it("ZEE et GRIB2 décochés au premier pixel", () => {
    assert.equal(DEFAULT_SHOW_ZEE, false);
    assert.equal(DEFAULT_SHOW_GRIB, false);
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../layers/useToggleLayers.js"),
      "utf8",
    );
    assert.match(src, /useState\(DEFAULT_SHOW_ZEE\)/);
    assert.match(src, /useState\(DEFAULT_SHOW_GRIB\)/);
    assert.equal(/useState\(true\).*showZee|showZee.*useState\(true\)/.test(src), false);
  });
});
