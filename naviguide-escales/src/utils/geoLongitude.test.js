import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { deltaLon, haversineNm, lerpLon, unwrapLon, wrapLon } from "./geo.js";
import { lerpLon as clockLerpLon } from "../engine/voyageClock.js";

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} ≉ ${b}`);

describe("geo.js — longitudes (module unique côté client)", () => {
  it("wrapLon replie dans [−180, 180] et garde les valeurs déjà bornées", () => {
    for (const x of [0.1, -0.1, 166.4567891234, -176.123456789, 180, -180]) {
      assert.equal(wrapLon(x), x);
    }
    near(wrapLon(181), -179);
    near(wrapLon(-181), 179);
    near(wrapLon(236.84), 236.84 - 360);
    near(wrapLon(540), 180);
    near(wrapLon(-540), -180);
    assert.ok(Number.isNaN(wrapLon(NaN)));
  });

  it("unwrapLon choisit la copie la plus proche", () => {
    assert.equal(unwrapLon(179, -179), 181);
    assert.equal(unwrapLon(-179, 179), -181);
    assert.equal(unwrapLon(-186, 166), -194);
    assert.equal(unwrapLon(null, 200), 200);
  });

  it("deltaLon donne l'écart signé le plus court", () => {
    near(deltaLon(-180, 179.85), -0.15);
    near(deltaLon(179, -179), 2);
    near(deltaLon(-176, 166), -18);
    assert.equal(deltaLon(10, 20), 10);
  });

  it("lerpLon suit le plus court arc et reste déplié autour de a", () => {
    near(lerpLon(-176, 166, 0.5), -185);
    near(wrapLon(lerpLon(-176, 166, 0.5)), 175);
    assert.equal(lerpLon(-185, -193, 0.5), -189);
    assert.equal(lerpLon(10, 20, 0.25), 12.5);
    for (let k = 0; k <= 10; k += 1) {
      const lon = lerpLon(-180, 179.85, k / 10);
      assert.ok(Math.abs(deltaLon(-180, lon)) <= 0.15 + 1e-9, `k=${k} lon=${lon}`);
    }
    assert.equal(lerpLon(null, 5, 0.5), 5);
  });

  it("voyageClock réexporte la même fonction (pas une deuxième copie)", () => {
    assert.equal(clockLerpLon, lerpLon);
  });

  it("haversineNm ne fait pas le tour du globe à l'antiméridien", () => {
    const a = haversineNm(-20, 179.9, -20, -179.9);
    assert.ok(a < 15, `${a} nm`);
    assert.ok(!Number.isFinite(haversineNm(0, 0, 0, Infinity)), "Infinity ne doit pas boucler");
  });
});
