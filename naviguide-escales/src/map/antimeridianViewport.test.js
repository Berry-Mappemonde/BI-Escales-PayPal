/*
 * Parcours du 18/10 (NAV-D-07) : carte vue au-delà de l'antiméridien
 * (centre lon 183, zoom 7, vue 176 → 190, ou 182 → 213 en panoramique).
 * Les requêtes catalogue partent avec des longitudes dépliées (> 180) : c'est
 * voulu, le serveur les accepte (copies ±360). La carte ne doit jamais
 * demander de tuile hors [0, 2^z) ni perdre un objet situé à -176.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { lonToTileX, visibleClimoTiles } from "../utils/atlasPoint.js";
import { pointInBounds, quantizedCatalogBbox } from "../layers/spatialFeatures.js";
import { wrapLon } from "../utils/geo.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (file) => readFileSync(join(here, file), "utf8");

const PAST_SEAM = { west: 175.968, east: 190.031, south: -18, north: -10 };
const FAR_EAST = { west: 182, east: 213, south: -22.5, north: -5.6 };

describe("vue au-delà de l'antiméridien (centre lon 183)", () => {
  it("les tuiles de fond restent repliées par Leaflet (noWrap: false partout)", () => {
    const scene = read("MapSceneController.js");
    assert.match(scene, /noWrap:\s*false/);
    for (const file of ["MapSceneController.js", "../layers/useToggleLayers.js", "../hooks/useSimulatorMap.js"]) {
      assert.doesNotMatch(read(file), /noWrap:\s*true/, file);
    }
  });

  it("le centre lon 183 désigne la même tuile que -177 une fois replié", () => {
    for (const z of [5, 6, 7]) {
      const n = 2 ** z;
      const x = ((lonToTileX(183, z) % n) + n) % n;
      assert.equal(x, lonToTileX(wrapLon(183), z));
      assert.ok(x >= 0 && x < n);
    }
  });

  it("tuiles climatologie : x toujours dans [0, 2^z) pour une vue 176 → 190 ou 182 → 213", () => {
    for (const bounds of [PAST_SEAM, FAR_EAST]) {
      for (const z of [3, 5, 6]) {
        const tiles = visibleClimoTiles(bounds, z);
        assert.ok(tiles.length > 0);
        for (const t of tiles) assert.ok(t.x >= 0 && t.x < 2 ** z, `z${z} x=${t.x}`);
      }
    }
  });

  it("catalogue : bbox dépliée envoyée telle quelle, objets à -176 gardés à l'écran", () => {
    const bbox = quantizedCatalogBbox(FAR_EAST, 7).split(",").map(Number);
    assert.ok(bbox[0] >= 180 && bbox[2] > bbox[0], String(bbox));
    assert.equal(pointInBounds(-176.2, -13.3, FAR_EAST), true);  // Mata-Utu
    assert.equal(pointInBounds(-171.8, -13.8, FAR_EAST), true);  // Apia
    assert.equal(pointInBounds(-176.2, -13.3, PAST_SEAM), true);
    assert.equal(pointInBounds(178.4, -17.5, PAST_SEAM), true);  // Viti Levu, côté ouest de la couture
  });
});
