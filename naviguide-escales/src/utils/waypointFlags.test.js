import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  cameraLngForBoat,
  drawingPinHtml,
  drawingPinMetrics,
  DRAWING_PIN_PX,
  flagIconMetrics,
  flagMarkerHtml,
  lonOnCameraCopy,
  markerWorldLngs,
  waypointFlagSrcs,
  worldCopyLngs,
  wrapLon,
} from "./waypointFlags.js";

describe("waypointFlagSrcs", () => {
  it("préfère flags[] (Nouméa Kanak + FR)", () => {
    assert.deepEqual(waypointFlagSrcs({ flag: "a", flags: ["kanak", "france"] }), ["kanak", "france"]);
    assert.deepEqual(waypointFlagSrcs({ flag: "solo" }), ["solo"]);
    assert.deepEqual(waypointFlagSrcs({ flag: "" }), []);
    assert.deepEqual(waypointFlagSrcs({ flags: [] }), []);
  });

  it("divIcon 1 ou 2 images", () => {
    const one = flagMarkerHtml(["/k.png"]);
    const two = flagMarkerHtml(["/k.png", "/fr.png"], [3, -2]);
    assert.equal((one.match(/<img/g) || []).length, 1);
    assert.equal((two.match(/<img/g) || []).length, 2);
    assert.match(two, /translate\(3px,-2px\)/);
    assert.deepEqual(flagIconMetrics(["a"]).iconSize[0] < flagIconMetrics(["a", "b"]).iconSize[0], true);
  });

  it("IconAnchor au centre exact du rond", () => {
    const m = drawingPinMetrics();
    assert.equal(DRAWING_PIN_PX, 14);
    assert.deepEqual(m.iconSize, [14, 14]);
    assert.deepEqual(m.iconAnchor, [7, 7]);
    assert.equal(m.iconAnchor[0], m.iconSize[0] / 2);
    assert.equal(m.iconAnchor[1], m.iconSize[1] / 2);
    const first = drawingPinHtml(0, ` data-testid="waypoint-flag"`);
    const next = drawingPinHtml(1);
    assert.match(first, /#22c55e/);
    assert.match(next, /#e2e8f0/);
    assert.match(first, /width:14px;height:14px/);
    assert.match(first, /box-sizing:border-box/);
    assert.match(first, /data-testid="waypoint-flag"/);
  });
});

describe("lonOnCameraCopy / worldCopyLngs", () => {
  it("aligne la copie sur la caméra près de 180°", () => {
    assert.deepEqual(worldCopyLngs(166.4), [166.4, 526.4, -193.6]);
    assert.equal(lonOnCameraCopy(166.4, 170), 166.4);
    assert.equal(lonOnCameraCopy(166.4, 520), 526.4);
    assert.equal(lonOnCameraCopy(166.4, -190), -193.6);
  });

  it("Mata-Utu → Nouméa : caméra et marqueur partagent la même copie", () => {
    const clockLon = -191.15750951788723;
    const apiLon = 168.835844780904;
    assert.equal(wrapLon(clockLon), clockLon + 360);
    assert.ok(Math.abs(wrapLon(clockLon) - apiLon) < 0.02);
    assert.equal(cameraLngForBoat(clockLon, null), clockLon);
    assert.equal(cameraLngForBoat(clockLon, wrapLon(clockLon)), wrapLon(clockLon));
    const afterJump = cameraLngForBoat(clockLon, apiLon);
    assert.ok(Math.abs(afterJump - apiLon) < 0.02);
    const lngs = markerWorldLngs(clockLon, afterJump);
    assert.equal(lngs[0], afterJump);
    assert.ok(lngs.some((lng) => Math.abs(lng - clockLon) < 1e-6));
    assert.ok(lngs.some((lng) => Math.abs(lng - wrapLon(clockLon)) < 1e-6));
  });

  it("sans centre caméra, le primaire reste la lon horloge (même copie que le sillage)", () => {
    assert.equal(lonOnCameraCopy(-191.16, null), -191.16);
    assert.equal(markerWorldLngs(-191.16, null)[0], -191.16);
    assert.ok(markerWorldLngs(-191.16, null).some((lng) => Math.abs(lng - wrapLon(-191.16)) < 1e-6));
  });
});

describe("Nouméa", () => {
  it("waypoints.js expose Kanak + français", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../constants/waypoints.js"),
      "utf8",
    );
    assert.match(src, /"Nouméa \(Nouvelle-Calédonie\)":\s+\[nouvelleCaledonie, france\]/);
  });

  it("itineraryPoints pose flags: [kanak, france]", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../constants/itineraryPoints.ts"),
      "utf8",
    );
    assert.match(src, /name: "Nouméa \(Nouvelle-Calédonie\)"[\s\S]{0,180}flags: \[nouvelleCaledonie, france\]/);
  });
});
