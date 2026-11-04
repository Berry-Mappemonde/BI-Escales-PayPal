import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { REGIME_COLORS, traveledEraSpeed, traveledRegimeSegments } from "./regimeRoute.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("useRouteLayer — teinte par régime", () => {
  it("colore le parcours jusqu'à traveledNm et fusionne les pas d'un même régime", () => {
    const verts = [
      { sailNm: 0, lat: 46.1, lon: -1.2, regime: "hindcast" },
      { sailNm: 10, lat: 45.5, lon: -3, regime: "hindcast" },
      { sailNm: 20, lat: 45.0, lon: -5, regime: "forecast" },
      { sailNm: 40, lat: 44.0, lon: -8, regime: "climatology" },
    ];
    const segs = traveledRegimeSegments(verts, 25);
    assert.equal(segs.length, 3);
    assert.equal(segs[0].regime, "hindcast");
    assert.equal(segs[1].regime, "forecast");
    assert.equal(segs[2].regime, "climatology");
    assert.ok(segs[0].coords.length >= 2);
    assert.equal(REGIME_COLORS.hindcast, "#2dd4bf");
    assert.equal(REGIME_COLORS.forecast, "#38bdf8");
    assert.equal(REGIME_COLORS.climatology, "#c084fc");
  });

  it("ne teinte pas une jambe avion", () => {
    const verts = [
      { sailNm: 0, lat: 4.9, lon: -52.3, regime: "climatology", vehicle: "main" },
      { sailNm: 10, lat: 20, lon: -58, regime: "climatology", vehicle: "plane" },
      { sailNm: 20, lat: 44.6, lon: -63.6, regime: "climatology", vehicle: "main" },
    ];
    const segs = traveledRegimeSegments(verts, 20);
    assert.equal(segs.every((s) => s.regime), true);
    assert.ok(segs.every((s) => {
      const [[, lat0]] = s.coords;
      return lat0 < 10 || lat0 > 40;
    }));
  });

  it("ne teinte rien sans distance parcourue", () => {
    assert.deepEqual(traveledRegimeSegments([{ sailNm: 0, lat: 0, lon: 0 }], 0), []);
  });

  it("un segment parcouru expose sa vitesse d'époque", () => {
    const segs = traveledRegimeSegments([
      { sailNm: 0, lat: 46.1, lon: -1.2, regime: "hindcast", speedKnots: 7.4 },
      { sailNm: 20, lat: 45.0, lon: -5, regime: "hindcast", speedKnots: 7.4 },
    ], 20);
    assert.equal(segs.length, 1);
    assert.equal(segs[0].speedKnots, 7.4);
    assert.equal(traveledEraSpeed(segs[0]), 7.4);
  });

  it("une jambe avion n'expose pas de vitesse d'époque", () => {
    const segs = traveledRegimeSegments([
      { sailNm: 0, lat: 4.9, lon: -52.3, regime: "hindcast", speedKnots: 400, vehicle: "plane" },
      { sailNm: 20, lat: 44.6, lon: -63.6, regime: "hindcast", speedKnots: 400, vehicle: "plane" },
    ], 20);
    assert.equal(segs.length, 0);
    assert.equal(traveledEraSpeed({
      regime: "hindcast", speedKnots: 400, vehicle: "plane",
    }), null);
  });

  it("le hook peint l'overlay sans retirer la route principale", () => {
    const src = readFileSync(join(here, "useRouteLayer.js"), "utf8");
    assert.match(src, /paintMain/);
    assert.match(src, /traveledRegimeSegments/);
    assert.match(src, /REGIME_COLORS/);
    assert.match(src, /bindTooltip/);
    assert.match(src, /traveled-era-speed/);
  });
});
