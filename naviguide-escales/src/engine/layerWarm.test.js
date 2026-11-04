import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { MAX_PEARLS_SIM, flatFromCustomRoute, sampleLeg } from "./iciAlong.js";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  LAYER_DRAW_CAPS,
  createDraftWarmer,
  decimateByZoom,
  drawCapForZoom,
  geojsonFromDrawn,
  kickDraftPearls,
  kickLayerWarm,
  pointsFromCustomRoute,
  pointsWithinDrawCap,
} from "./layerWarm.js";

const line = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: [[-1.16, 46.15], [9.19, 41.31]],
    },
  }],
};

const DRAFT_POINTS = [
  { lat: 46.15, lon: -1.16, name: "La Rochelle" },
  { lat: 45.15, lon: -1.16 },
];
const DRAFT_SEGS = [{ coords: [[-1.16, 46.15], [-1.16, 45.15]] }];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function recorder() {
  const calls = [];
  const fake = (url, opts) => {
    calls.push({ url: String(url), opts: opts || {} });
    return Promise.resolve({ ok: true });
  };
  return { calls, fake };
}

function warmPosts(calls) {
  return calls.filter((c) => /\/ici\/layers\/warm$/.test(c.url));
}

function thinGets(calls) {
  return calls.filter((c) => /\/ici\?/.test(c.url) && /thin=1/.test(c.url));
}

describe("layerWarm", () => {
  it("extrait les sommets [lat, lon] d'une LineString", () => {
    assert.deepEqual(pointsFromCustomRoute(line), [[46.15, -1.16], [41.31, 9.19]]);
    assert.deepEqual(pointsFromCustomRoute(null), []);
    assert.deepEqual(pointsFromCustomRoute({ type: "FeatureCollection", features: [] }), []);
  });

  it("lit aussi un MultiLineString et ignore un polygone", () => {
    const mixed = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: {
            type: "MultiLineString",
            coordinates: [[[-17.8, 18.2], [-16.9, 17.6]]],
          },
        },
        {
          type: "Feature",
          geometry: {
            type: "Polygon",
            coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
          },
        },
      ],
    };
    assert.deepEqual(pointsFromCustomRoute(mixed), [[18.2, -17.8], [17.6, -16.9]]);
  });

  it("POST /ici/layers/warm sans bloquer, et ne lance rien sans points", () => {
    const { calls, fake } = recorder();
    assert.equal(kickLayerWarm({ type: "FeatureCollection", features: [] }, fake), false);
    assert.equal(calls.length, 0);
    assert.equal(kickLayerWarm(line, fake), true);
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/ici\/layers\/warm$/);
    assert.equal(calls[0].opts.method, "POST");
    const body = JSON.parse(calls[0].opts.body);
    assert.deepEqual(body.points, [[46.15, -1.16], [41.31, 9.19]]);
  });
});

describe("layerWarm — brouillon pendant le tracé", () => {
  it("construit un GeoJSON LineString depuis drawnPoints / drawnSegments", () => {
    const geo = geojsonFromDrawn(DRAFT_POINTS, DRAFT_SEGS);
    assert.equal(geo.type, "FeatureCollection");
    assert.equal(geo.features[0].geometry.type, "LineString");
    assert.deepEqual(pointsFromCustomRoute(geo).slice(0, 2), [[46.15, -1.16], [45.15, -1.16]]);
    assert.equal(kickLayerWarm(geo, recorder().fake), true);
  });

  it("debounce : trois clics rapides → un seul POST /ici/layers/warm", async () => {
    const { calls, fake } = recorder();
    const warmer = createDraftWarmer({ fetchImpl: fake, debounceMs: 20 });
    warmer.schedule(line);
    warmer.schedule(line);
    warmer.schedule(line);
    await sleep(8);
    assert.equal(warmPosts(calls).length, 0);
    await sleep(30);
    assert.equal(warmPosts(calls).length, 1);
  });

  it("Annuler avant le debounce : le mock n'est plus appelé ; pas de vidage de cache", async () => {
    const { calls, fake } = recorder();
    const warmer = createDraftWarmer({ fetchImpl: fake, debounceMs: 20 });
    warmer.schedule(line);
    warmer.cancel();
    await sleep(40);
    assert.equal(calls.length, 0);
    assert.equal(calls.some((c) => /flush|clear|invalidate|purge|\/kv/i.test(c.url)), false);
    assert.equal(calls.some((c) => c.opts.method === "DELETE"), false);
  });

  it("Annuler après le départ coupe les vols suivants", async () => {
    let calls = 0;
    const fake = () => {
      calls += 1;
      return new Promise(() => {});
    };
    const warmer = createDraftWarmer({ fetchImpl: fake, debounceMs: 10 });
    warmer.schedule(line);
    await sleep(25);
    assert.ok(calls >= 1);
    const n = calls;
    warmer.cancel();
    await sleep(30);
    assert.equal(calls, n);
  });

  it("ne renvoie pas les cellules déjà envoyées ; le cache serveur n'est pas vidé", async () => {
    const { calls, fake } = recorder();
    const warmer = createDraftWarmer({ fetchImpl: fake, debounceMs: 10 });
    warmer.schedule(line);
    await sleep(25);
    assert.equal(warmPosts(calls).length, 1);
    warmer.schedule(line);
    await sleep(25);
    assert.equal(warmPosts(calls).length, 1);
    assert.equal(calls.some((c) => /flush|clear|invalidate|purge/i.test(c.url)), false);
  });

  it("GET /ici?thin=1 sur le brouillon, cap MAX_PEARLS_SIM, pas les perles Berry", async () => {
    const { calls, fake } = recorder();
    const geo = geojsonFromDrawn(DRAFT_POINTS, DRAFT_SEGS);
    const warmer = createDraftWarmer({ fetchImpl: fake, debounceMs: 10 });
    warmer.schedule(geo);
    await sleep(25);
    assert.ok(thinGets(calls).length >= 1, "au moins une perle mince du trait");
    assert.equal(calls.some((c) => /\/ici\/pearls/.test(c.url)), false);
    assert.ok(thinGets(calls).length <= MAX_PEARLS_SIM);
    const long = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: Array.from({ length: 90 }, (_, i) => [-1.16 - i, 46.15]),
        },
      }],
    };
    const { calls: longCalls, fake: longFake } = recorder();
    assert.equal(kickDraftPearls(long, longFake, { maxPearls: MAX_PEARLS_SIM }), true);
    await sleep(15);
    assert.ok(thinGets(longCalls).length <= MAX_PEARLS_SIM);
    const flat = flatFromCustomRoute(geo);
    const pearls = sampleLeg(flat, { maxPearls: MAX_PEARLS_SIM });
    assert.ok(pearls.length >= 1 && pearls.length <= MAX_PEARLS_SIM);
    assert.ok(pearls.every((p) => p.lat > 44 && p.lat < 47 && p.lon < 0));
  });
});

describe("décimation au zoom — plafond par calque", () => {
  it("zoom non fini : plafond plein ; plus bas, le facteur ne descend pas sous 24", () => {
    assert.equal(drawCapForZoom(Number.NaN, LAYER_DRAW_CAPS.wind), LAYER_DRAW_CAPS.wind);
    assert.equal(drawCapForZoom(2, LAYER_DRAW_CAPS.wind), Math.round(LAYER_DRAW_CAPS.wind * 0.45));
    assert.equal(drawCapForZoom(3, LAYER_DRAW_CAPS.point), Math.round(LAYER_DRAW_CAPS.point * 0.45));
    assert.equal(drawCapForZoom(4, LAYER_DRAW_CAPS.wave), Math.round(LAYER_DRAW_CAPS.wave * 0.7));
    assert.equal(drawCapForZoom(5, LAYER_DRAW_CAPS.current), Math.round(LAYER_DRAW_CAPS.current * 0.7));
    assert.equal(drawCapForZoom(8, LAYER_DRAW_CAPS.grib), Math.max(24, Math.round(LAYER_DRAW_CAPS.grib * 0.85)));
    assert.equal(drawCapForZoom(9, LAYER_DRAW_CAPS.arrow), LAYER_DRAW_CAPS.arrow);
    assert.ok(drawCapForZoom(1, 10) <= 10);
    assert.ok(drawCapForZoom(1, LAYER_DRAW_CAPS.wind) >= 24);
  });

  it("deux points restent, une grille dense est coupée, les polygones restent", () => {
    const two = [{ geometry: { type: "Point" } }, { geometry: { type: "Point" } }];
    assert.equal(decimateByZoom(two, 2, LAYER_DRAW_CAPS.point).length, 2);
    const dense = Array.from({ length: 800 }, (_, i) => ({ id: i, geometry: { type: "Point" } }));
    const cut = decimateByZoom(dense, 2, LAYER_DRAW_CAPS.point);
    assert.ok(cut.length <= drawCapForZoom(2, LAYER_DRAW_CAPS.point));
    assert.ok(cut.length >= 24);
    const polygon = { geometry: { type: "Polygon", coordinates: [] } };
    const mixed = pointsWithinDrawCap([polygon, ...dense], 2, LAYER_DRAW_CAPS.point);
    assert.equal(mixed[0], polygon);
    assert.ok(mixed.length < dense.length);
  });

  it("les calques dessinent avec ce plafond, sans réécrire le canvas", () => {
    const root = join(dirname(fileURLToPath(import.meta.url)), "..");
    const climo = readFileSync(join(root, "layers/useClimatologyLayer.js"), "utf8");
    const catalog = readFileSync(join(root, "layers/spatialCatalogLayer.js"), "utf8");
    const grib = readFileSync(join(root, "layers/useGribCorridorLayer.js"), "utf8");
    const points = readFileSync(join(root, "layers/points.js"), "utf8");
    assert.match(climo, /drawCapForZoom\(map\.getZoom\(\), CLIMO_DRAW_CAPS/);
    assert.match(catalog, /pointsWithinDrawCap/);
    assert.match(grib, /decimateByZoom\(/);
    assert.match(points, /L\.canvas/);
    assert.doesNotMatch(catalog, /L\.canvas\s*=/);
  });
});
