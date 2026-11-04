import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  CLIMO_WORLD_MAX_FEATURES,
  climoMeshDeg,
  climoViewKey,
  decimateClimoFeatures,
  naiveRebuildKeys,
  publishSameViewWindSync,
  reattachClimoPool,
  resetClimoRoseStats,
  syncClimoPointMarkers,
  visibleClimoLngs,
} from "./climoRoseMarkers.js";
import { climoPointLngs } from "./climatologyWorld.js";

const hookSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "useClimatologyLayer.js"),
  "utf8",
);

function feature(lon, lat) {
  return { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: {} };
}

function fakeGroup() {
  const layers = new Set();
  return {
    layers,
    addLayer(lyr) { layers.add(lyr); },
    removeLayer(lyr) { layers.delete(lyr); },
  };
}

describe("climoMeshDeg (maille RD8)", () => {
  it("z ≤ 2 → 4°, z = 3 → 2°, z ≥ 4 → 1°", () => {
    assert.equal(climoMeshDeg(0), 16);
    assert.equal(climoMeshDeg(1), 8);
    assert.equal(climoMeshDeg(2), 4);
    assert.equal(climoMeshDeg(3), 2);
    assert.equal(climoMeshDeg(4), 1);
    assert.equal(climoMeshDeg(6), 1);
  });
});

describe("decimateClimoFeatures — zoom monde sous le plafond", () => {
  it("une grille 1° mondiale à z=2 tient sous 90×45 cellules 4°", () => {
    const dense = [];
    for (let lat = -89; lat <= 89; lat += 1) {
      for (let lon = -179; lon <= 179; lon += 1) {
        dense.push(feature(lon, lat));
      }
    }
    const world = decimateClimoFeatures(dense, 2);
    assert.ok(world.length <= CLIMO_WORLD_MAX_FEATURES);
    assert.ok(world.length <= 90 * 45);
    assert.ok(world.length > 200);
    assert.ok(world.length < dense.length / 8);
  });
});

describe("visibleClimoLngs", () => {
  it("Atlantique : une copie, pas les ±360°", () => {
    const lngs = visibleClimoLngs(climoPointLngs(-40), { west: -60, east: -10 });
    assert.deepEqual(lngs, [-40]);
  });

  it("vue monde : une seule copie, la plus proche du centre", () => {
    const lngs = visibleClimoLngs(climoPointLngs(170), { west: -180, east: 180 });
    assert.deepEqual(lngs, [170]);
    assert.equal(climoPointLngs(170).length, 3);
  });

  it("Pacifique près de 180° : copie +360 si elle est dans la vue", () => {
    const lngs = visibleClimoLngs(climoPointLngs(-170), { west: 160, east: 200 });
    assert.deepEqual(lngs, [190]);
  });
});

describe("syncClimoPointMarkers — réutilisation", () => {
  it("deux passes sur la même vue ne recréent pas les marqueurs", () => {
    const features = [feature(-40, 20), feature(-30, 25), feature(-20, 15)];
    const group = fakeGroup();
    const pool = new Map();
    let built = 0;
    const makeLayer = (ll) => {
      built += 1;
      return { id: ll.join(",") };
    };
    const bounds = { west: -60, east: -5 };
    const first = syncClimoPointMarkers({
      group, pool, features, zoom: 4, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    assert.equal(first.created, 3);
    assert.equal(first.reused, 0);
    assert.equal(built, 3);
    assert.equal(naiveRebuildKeys(features).length, 9);

    const second = syncClimoPointMarkers({
      group, pool, features, zoom: 4, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    assert.equal(second.created, 0);
    assert.equal(second.reused, 3);
    assert.equal(second.removed, 0);
    assert.equal(built, 3);
    assert.equal(pool.size, 3);
    assert.equal(group.layers.size, 3);
  });

  it("le rebuild ×3 coûte plus de clés que la vue Atlantique", () => {
    const features = [];
    for (let lat = 0; lat <= 40; lat += 1) {
      for (let lon = -60; lon <= -20; lon += 1) {
        features.push(feature(lon, lat));
      }
    }
    const group = fakeGroup();
    const pool = new Map();
    const makeLayer = (ll) => ({ id: String(ll) });
    const bounds = { west: -80, east: 0 };
    const t0 = performance.now();
    syncClimoPointMarkers({
      group, pool, features, zoom: 4, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    const t1 = performance.now();
    const second = syncClimoPointMarkers({
      group, pool, features, zoom: 4, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    const t2 = performance.now();
    const oldKeys = naiveRebuildKeys(features).length;
    assert.equal(second.created, 0);
    assert.ok(oldKeys >= second.markers * 3);
    assert.ok(t2 - t1 < 50);
    console.log(
      `[rf9 bench] features=${features.length} oldKeys=${oldKeys} markers=${second.markers}`
      + ` firstMs=${(t1 - t0).toFixed(1)} reuseMs=${(t2 - t1).toFixed(1)}`,
    );
  });
});

describe("useClimatologyLayer — zoomend débouncé, pas pendant l'animation", () => {
  it("écoute zoomstart/zoomend/moveend et garde l'annulation", () => {
    assert.match(hookSrc, /zoomstart/);
    assert.match(hookSrc, /VIEW_DEBOUNCE_MS/);
    assert.match(hookSrc, /_animatingZoom/);
    assert.match(hookSrc, /AbortController/);
    assert.match(hookSrc, /climoPointLngs/);
    assert.match(hookSrc, /syncClimoPointMarkers/);
    assert.doesNotMatch(hookSrc, /addPointMarkers/);
    assert.match(hookSrc, /loadClimoLayerFeatures/);
    assert.match(hookSrc, /climoViewKey/);
    assert.match(hookSrc, /publishSameViewWindSync/);
    assert.match(hookSrc, /SHARED/);
    assert.match(hookSrc, /reattachClimoPool/);
    assert.match(hookSrc, /!\(features \|\| \[\]\)\.length && pool\.size/);
    assert.doesNotMatch(hookSrc, /resetClimoRoseStats\(\);\s*let windSyncs/);
  });
});

describe("climoViewKey", () => {
  it("même cadre → même clé", () => {
    const bounds = {
      getWest: () => -60.1234,
      getSouth: () => 0.1,
      getEast: () => -20.5,
      getNorth: () => 40.9,
    };
    const map = { getZoom: () => 3.2, getBounds: () => bounds };
    assert.equal(climoViewKey(map), climoViewKey(map));
    assert.equal(climoViewKey(map), "3:-60.123:0.100:-20.500:40.900");
  });
});

describe("publishSameViewWindSync + reattach — 2e passe / remontage", () => {
  it("ne crée aucun marqueur et republie created=0", () => {
    resetClimoRoseStats();
    const features = [feature(-40, 20), feature(-30, 25)];
    const pool = new Map();
    const makeLayer = (ll) => ({ id: ll.join(",") });
    const bounds = { west: -60, east: -5 };
    const g1 = fakeGroup();
    const first = syncClimoPointMarkers({
      group: g1, pool, features, zoom: 3, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    assert.equal(first.created, 2);
    const g2 = fakeGroup();
    const second = syncClimoPointMarkers({
      group: g2, pool, features, zoom: 3, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    assert.equal(second.created, 0);
    assert.equal(second.reused, 2);
    assert.equal(g2.layers.size, 2);
    const published = publishSameViewWindSync(pool, 3);
    assert.equal(published.created, 0);
    assert.equal(published.markers, 2);
    assert.equal(published.syncs, 3);
  });

  it("ne vide pas le pool si le cadre ne retient aucune copie", () => {
    const features = [feature(-40, 20)];
    const group = fakeGroup();
    const pool = new Map();
    const makeLayer = (ll) => ({ id: ll.join(",") });
    const bounds = { west: -60, east: -5 };
    syncClimoPointMarkers({
      group, pool, features, zoom: 3, bounds, makeLayer,
      copiesFor: (lon) => visibleClimoLngs(climoPointLngs(lon), bounds),
    });
    assert.equal(pool.size, 1);
    const wiped = syncClimoPointMarkers({
      group, pool, features, zoom: 3, bounds, makeLayer,
      copiesFor: () => [],
    });
    assert.equal(wiped.created, 0);
    assert.equal(wiped.removed, 0);
    assert.equal(wiped.markers, 1);
    assert.equal(pool.size, 1);
  });
});
