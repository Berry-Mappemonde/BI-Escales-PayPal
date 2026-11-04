import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { followMinZoom, worldViewZoom, worldWidthPx } from "./zoomFloor.js";

describe("zoomFloor — plancher de dézoom en Suivre (27 sept.)", () => {
  it("le monde tient au plus une fois dans l'écran, au pas de zoom de la carte", () => {
    for (const [w, h] of [[1440, 820], [1024, 768], [800, 1200], [2560, 1440], [390, 844]]) {
      const z = followMinZoom({ x: w, y: h }, 0.25);
      assert.ok(worldWidthPx(z) >= Math.max(w, h), `monde ${worldWidthPx(z)}px ≥ écran ${Math.max(w, h)} à z=${z}`);
      assert.ok(worldWidthPx(z - 0.25) < Math.max(w, h), `un cran de moins montrerait le monde deux fois (z=${z})`);
      assert.equal(Math.round(z * 4) / 4, z, "aligné sur zoomSnap 0.25");
    }
  });

  it("écran 1440 px → 2.5 ; écran 1024 px → 2 ; taille inconnue → plancher d'origine", () => {
    assert.equal(followMinZoom({ x: 1440, y: 820 }), 2.5);
    assert.equal(followMinZoom({ x: 1024, y: 700 }), 2);
    assert.equal(followMinZoom(null), 0);
    assert.equal(followMinZoom({ x: 0, y: 0 }, 0.25, 1), 1);
  });

  it("Vue monde une fois : jamais sous le plancher (1280 px → 2.5)", () => {
    assert.equal(worldViewZoom({ x: 1280, y: 800 }, 0.25, 2), 2.5);
    assert.equal(worldViewZoom({ x: 1024, y: 700 }, 0.25, 2), 2);
    assert.ok(worldWidthPx(worldViewZoom({ x: 1280, y: 800 }, 0.25, 2)) >= 1280);
  });
});
