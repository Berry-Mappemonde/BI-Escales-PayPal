import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import {
  COMPACT_ATTRIBUTION_BELOW_PX,
  isCompactAttribution,
  popoverPlacement,
} from "./compactAttribution.js";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "../index.css"), "utf8");
const scene = readFileSync(join(here, "../map/MapSceneController.js"), "utf8");

describe("crédits compacts (carte visible étroite)", () => {
  it("passe en bouton sous 260 px de carte visible, bande complète au-delà", () => {
    assert.equal(COMPACT_ATTRIBUTION_BELOW_PX, 260);
    assert.equal(isCompactAttribution(62), true);
    assert.equal(isCompactAttribution(259), true);
    assert.equal(isCompactAttribution(260), false);
    assert.equal(isCompactAttribution(374), false);
    assert.equal(isCompactAttribution(Number.NaN), false);
  });

  it("garde les crédits ouverts dans l'écran, au moins 300 px de large", () => {
    // Panneau gauche ouvert à 390 px : bouton au bord droit de la carte visible.
    const left = popoverPlacement({ left: 362, right: 382, top: 700 }, 390, 844);
    assert.deepEqual(left, { right: 8, bottom: 148, maxWidth: 374, maxHeight: 688 });
    // Panneau outils ouvert : le bouton est à gauche, la boîte s'élargit vers la droite.
    const tools = popoverPlacement({ left: 50, right: 70, top: 700 }, 390, 844);
    assert.equal(tools.right, 82);
    assert.equal(tools.maxWidth, 300);
    assert.ok(tools.right >= 8 && tools.right + tools.maxWidth <= 390 - 8);
  });

  it("le bouton remplace la bande en mode compact, la scène l'installe", () => {
    assert.match(css, /\.leaflet-container\.naviguide-attrib-compact \.leaflet-bottom\.leaflet-right \.leaflet-control-attribution \{ display: none; \}/);
    assert.match(css, /\.leaflet-container\.naviguide-attrib-compact \.leaflet-bottom\.leaflet-right \{[^}]*flex-direction:\s*column/);
    assert.match(css, /\.naviguide-attrib-popover \{[^}]*position:\s*fixed/);
    assert.match(scene, /installCompactAttribution\(map\)/);
    assert.match(scene, /releaseCompactAttribution\?\.\(\)/);
  });
});
