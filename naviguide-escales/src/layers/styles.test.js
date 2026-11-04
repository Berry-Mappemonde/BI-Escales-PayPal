import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX, TILE_ATTRIBUTION, tileAttribution } from "./styles.js";
import { FILM_BAR_BOTTOM_GAP_PX, FILM_BAR_HEIGHT_PX, mapInsetVars } from "../utils/filmBarLayout.js";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "../index.css"), "utf8");

describe("TILE_ATTRIBUTION", () => {
  it("crédite Esri une seule fois et quatre ancres (Esri, HERE, Garmin, OSM)", () => {
    const anchors = [...TILE_ATTRIBUTION.matchAll(/<a\b[^>]*>([^<]*)<\/a>/g)];
    assert.equal(anchors.length, 4);
    assert.deepEqual(anchors.map((m) => m[1]), [
      "Esri",
      "HERE",
      "Garmin",
      "OpenStreetMap contributors",
    ]);
    const esriHits = TILE_ATTRIBUTION.match(/Esri/g) || [];
    assert.equal(esriHits.length, 1, "le mot Esri une seule fois dans toute la chaîne");
    assert.match(TILE_ATTRIBUTION, /Tuiles/);
    assert.match(tileAttribution("en"), /Tiles/);
    assert.doesNotMatch(tileAttribution("en"), /Tuiles/);
    assert.match(anchors[0][0], /href="https:\/\/www\.esri\.com\/"/);
    assert.match(TILE_ATTRIBUTION, /href="https:\/\/www\.here\.com\/"/);
    assert.match(TILE_ATTRIBUTION, /href="https:\/\/www\.garmin\.com\/"/);
    assert.match(TILE_ATTRIBUTION, /href="https:\/\/www\.openstreetmap\.org\/copyright"/);
  });
});

describe("crédits Leaflet — marge ≥ hauteur barre", () => {
  it("l'inset bas des crédits dépasse ou égale la hauteur de la barre film", () => {
    assert.ok(LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX >= FILM_BAR_HEIGHT_PX.controls);
    assert.ok(LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX >= FILM_BAR_HEIGHT_PX.compact);
    assert.equal(
      LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX,
      FILM_BAR_HEIGHT_PX.controls + FILM_BAR_BOTTOM_GAP_PX,
    );
    const sim = mapInsetVars({ filmBarVisible: true, filmBarControls: true });
    const suivre = mapInsetVars({ filmBarVisible: true, filmBarControls: false });
    assert.ok(parseInt(sim["--sim-inset-bottom"], 10) >= FILM_BAR_HEIGHT_PX.controls);
    assert.ok(parseInt(suivre["--sim-inset-bottom"], 10) >= FILM_BAR_HEIGHT_PX.compact);
    assert.ok(parseInt(sim["--sim-inset-bottom"], 10) >= LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX);
    assert.match(css, /--sim-inset-bottom/);
    assert.match(css, /\.leaflet-control-attribution/);
  });
});
