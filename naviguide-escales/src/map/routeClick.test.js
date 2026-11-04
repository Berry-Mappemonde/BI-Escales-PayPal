import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isNearRoute, pointToSegmentPx, ROUTE_CLICK_THRESHOLD_PX } from "./routeClick.js";

const here = dirname(fileURLToPath(import.meta.url));

/** Projection équirectangulaire : 1° = 10 px, suffisant pour le seuil de 16 px. */
function mockMap() {
  return {
    latLngToLayerPoint(latlng) {
      const lat = Array.isArray(latlng) ? latlng[0] : latlng.lat;
      const lon = Array.isArray(latlng) ? latlng[1] : latlng.lng;
      return { x: lon * 10, y: -lat * 10 };
    },
  };
}

const SEA = { coords: [[-1.2, 46.1], [-1.0, 46.2]] };
const AIR = { coords: [[-1.2, 46.1], [-1.0, 46.2]], kind: "air" };

describe("pointToSegmentPx — copies du monde", () => {
  it("garde le seuil à 16 px", () => {
    assert.equal(ROUTE_CLICK_THRESHOLD_PX, 16);
  });

  it("un clic à lng+360 d'un segment mer appelle onRouteClick", () => {
    const map = mockMap();
    const clickLat = 46.15;
    const clickLon = -1.1 + 360;
    assert.ok(pointToSegmentPx(map, clickLat, clickLon, SEA.coords) < ROUTE_CLICK_THRESHOLD_PX);
    let called = 0;
    if (isNearRoute(map, clickLat, clickLon, [SEA])) called += 1;
    assert.equal(called, 1);
  });

  it("un clic à lng−360 d'un segment mer appelle aussi onRouteClick", () => {
    const map = mockMap();
    assert.equal(isNearRoute(map, 46.15, -1.1 - 360, [SEA]), true);
  });

  it("un clic sur la copie de base reste un hit", () => {
    const map = mockMap();
    assert.equal(isNearRoute(map, 46.15, -1.1, [SEA]), true);
  });

  it("un clic loin du trait ne déclenche pas onRouteClick, même après wrap", () => {
    const map = mockMap();
    let called = 0;
    if (isNearRoute(map, 10, -1.1 + 360, [SEA])) called += 1;
    assert.equal(called, 0);
    assert.ok(pointToSegmentPx(map, 10, -1.1 + 360, SEA.coords) > ROUTE_CLICK_THRESHOLD_PX);
  });

  it("ignore une jambe avion même sous le curseur", () => {
    const map = mockMap();
    assert.equal(isNearRoute(map, 46.15, -1.1, [AIR]), false);
    assert.equal(isNearRoute(map, 46.15, -1.1 + 360, [AIR]), false);
  });

  it("MapScene délègue le hit-test à isNearRoute (seuil inchangé)", () => {
    const src = readFileSync(join(here, "MapScene.jsx"), "utf8");
    assert.match(src, /import \{ isNearRoute \} from "\.\/routeClick\.js"/);
    assert.match(src, /if \(isNearRoute\(map, lat, lon, active\)\)/);
    assert.doesNotMatch(src, /pointToSegmentPx/);
    assert.doesNotMatch(src, /function pointToSegmentPx/);
  });
});
