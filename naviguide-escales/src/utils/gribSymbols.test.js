import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  beaufortColor,
  gribBarbSvg,
  gribDisplayPoints,
  pickGribSlice,
  waveHsColor,
  wmoBarbMarks,
  worldCopyLngs,
} from "./gribSymbols.js";

describe("gribSymbols", () => {
  it("encode les barbules OMM", () => {
    assert.deepEqual(wmoBarbMarks(0), { pennants: 0, longs: 0, shorts: 0, calm: true });
    assert.deepEqual(wmoBarbMarks(15), { pennants: 0, longs: 1, shorts: 1, calm: false });
    assert.deepEqual(wmoBarbMarks(50), { pennants: 1, longs: 0, shorts: 0, calm: false });
    assert.deepEqual(wmoBarbMarks(65), { pennants: 1, longs: 1, shorts: 1, calm: false });
  });

  it("teinte Beaufort et Hs comme la climatologie", () => {
    assert.equal(beaufortColor(0), "#94a3b8");
    assert.equal(beaufortColor(20), "#2dd4bf");
    assert.equal(beaufortColor(40), "#f97316");
    assert.equal(waveHsColor(0.8), "#5eead4");
    assert.equal(waveHsColor(2), "#0d9488");
    assert.equal(waveHsColor(4), "#155e75");
  });

  it("garde un point par maille, le plus proche de l’heure", () => {
    const slice = pickGribSlice([
      { lat: -13.3, lon: -176.2, t: "2026-09-15T12:00:00Z", windKnots: 8 },
      { lat: -13.3, lon: -176.2, t: "2026-09-15T18:00:00Z", windKnots: 14 },
      { lat: -14, lon: 166, t: "2026-09-15T18:00:00Z", windKnots: 11, hs: 1.6 },
    ], "2026-09-15T17:00:00Z");
    assert.equal(slice.length, 2);
    assert.equal(slice.find((s) => s.lon === -176.2).windKnots, 14);
  });

  it("dessine une hampe, pas un rectangle", () => {
    const svg = gribBarbSvg({ windKnots: 18, dirFromDeg: 240 });
    assert.match(svg, /<svg/);
    assert.match(svg, /rotate\(240/);
    assert.doesNotMatch(svg, /rect/i);
  });

  it("triple la longitude pour les copies monde", () => {
    assert.deepEqual(worldCopyLngs(166), [166, 526, -194]);
  });

  it("si une seule maille, pose un stencil 5×5 autour du bateau", () => {
    const pts = gribDisplayPoints([
      { lat: -21.6, lon: -186.2, t: "2026-09-15T18:00:00Z", windKnots: 14, dirFromDeg: 105, hs: 2.2 },
    ], { lat: -21.6, lon: -186.2, whenIso: "2026-09-15T18:00:00Z" });
    assert.equal(pts.length, 25);
    assert.ok(pts.every((p) => p.windKnots === 14));
    assert.ok(pts.some((p) => p.lat < -21.6 && p.lon < -186.2));
  });

  it("près de 180°, prend la maille de l’autre copie, pas l’Atlantique", () => {
    const pts = gribDisplayPoints([
      { lat: -22.7, lon: -191.16, t: "2026-09-16T03:00:00Z", windKnots: 14, dirFromDeg: 101, hs: 1.7 },
      { lat: 0, lon: 0, t: "2026-09-16T03:00:00Z", windKnots: 3, dirFromDeg: 10, hs: 0.4 },
    ], { lat: -22.7, lon: 168.84, whenIso: "2026-09-16T03:00:00Z" });
    assert.equal(pts.length, 25);
    assert.ok(pts.every((p) => p.windKnots === 14 && p.hs === 1.7));
    assert.ok(pts.some((p) => Math.abs(p.lon - 168.84) < 0.05));
  });
});

describe("couche GRIB", () => {
  it("n’utilise plus L.rectangle", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../layers/useGribCorridorLayer.js"),
      "utf8",
    );
    assert.equal(src.includes("L.rectangle"), false);
    assert.equal(src.includes("gribBarbSvg"), true);
    assert.equal(src.includes("markerWorldLngs"), true);
    assert.equal(src.includes("cameraLngForBoat"), true);
    assert.equal(src.includes('getPane("grib")'), true);
    assert.equal(src.includes('getPane("boat")'), false);
  });
});
