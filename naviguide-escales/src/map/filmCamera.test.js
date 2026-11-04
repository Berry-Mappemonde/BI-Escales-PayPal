import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FILM_BOAT_KEEP_FRAC, FILM_PAN_MAX_SCREEN } from "../engine/replay.js";
import {
  applyFilmCamera,
  clampFilmPan,
  clampFilmScreenStep,
  filmApproachZoom,
  filmChapterCenter,
  filmChapterZoom,
  filmIntraChapterCenter,
  filmLegIsArchipelago,
  FILM_ARCHIPELAGO_NM,
  FILM_FLIP_HOLD_MS,
  FILM_INTRA_JUMP_PX,
  FILM_INTERP_DELAY_MS,
  FILM_SCREEN_STEP_MAX_PX,
  FILM_TILE_SLOW,
  FILM_ZOOM_ARCHIPELAGO_MAX,
  filmPanMaxFrac,
  interpolateFilmSamples,
  keepBoatInFrame,
  preloadFilmTiles,
  pushFilmSample,
  smoothFilmHeading,
  stepFilmCamera,
  tilesAlongLeg,
} from "./filmCamera.js";

const here = dirname(fileURLToPath(import.meta.url));
const controller = readFileSync(join(here, "MapSceneController.js"), "utf8");

describe("filmCamera — premier mouvement = chapitre 1", () => {
  it("cadre la première jambe (Saint-Maur → La Rochelle), zoom [3 ; 7], sans flyTo", () => {
    const calls = [];
    const map = {
      flyTo(center, zoom) { calls.push({ action: "flyTo", center, zoom }); },
      setView(center, zoom, opts) { calls.push({ action: "setView", center, zoom, opts }); },
      getBoundsZoom() { return 6; },
      getSize() { return { x: 1280, y: 800 }; },
      getBounds() {
        return {
          getNorth: () => 20,
          getSouth: () => -40,
          getEast: () => 180,
          getWest: () => 120,
        };
      },
    };
    const leg = { fromLat: 46.8075, fromLon: 1.6358, toLat: 46.1541, toLon: -1.167 };
    const zoom = filmChapterZoom(map, leg);
    assert.ok(zoom >= 3 && zoom <= 7, `zoom chapitre 1 = ${zoom}`);

    const first = applyFilmCamera(map, {
      chapterIdx: 0,
      lastChapterIdx: null,
      lat: 46.8075,
      lon: 1.6358,
      heading: 260,
      zoom,
      now: 1000,
    });
    assert.equal(first.action, "setView");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].action, "setView");
    assert.deepEqual(calls[0].center, [46.8075, 1.6358], "pas d'offset vers l'Asie");
    assert.equal(calls[0].zoom, zoom);
    assert.equal(calls[0].opts?.animate, false);
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);

    const next = applyFilmCamera(map, {
      chapterIdx: 1,
      lastChapterIdx: first.lastChapterIdx,
      lat: 46.1541,
      lon: -1.167,
      heading: 140,
      zoom,
      now: 3000,
      lastSetViewAt: first.lastSetViewAt,
      flyingUntil: first.flyingUntil,
    });
    assert.equal(next.action, "setView");
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
    assert.equal(calls.filter((c) => c.action === "setView").length, 2);
  });

  it("MapSceneController : pas de flyTo / fitBounds sur la route entière au lancement ni au retour live", () => {
    assert.match(controller, /if \(!previous\.filmActive && this\.config\.filmActive\)/);
    assert.match(controller, /if \(previous\.filmActive && !this\.config\.filmActive\)/);
    assert.match(controller, /this\.camera\.recapture = this\.config\.cinemaRecapture/);
    assert.match(controller, /this\.camera\.filmZoomHold/);
    assert.match(controller, /this\.map\.setView\(\s*\[\s*live\.lat,\s*lonCam\s*\]/);
    assert.doesNotMatch(controller, /filmActive[\s\S]{0,80}fitBounds/);
    assert.doesNotMatch(controller, /filmActive[\s\S]{0,200}zoomForRemaining/);
  });
});

describe("filmCamera — pan borné, un setView par chapitre", () => {
  function fakeMap(center = { lat: 46, lng: -1 }) {
    const calls = [];
    let here = { ...center };
    const map = {
      flyTo(c, zoom) { calls.push({ action: "flyTo", center: c, zoom }); here = { lat: c[0], lng: c[1] }; },
      setView(c, zoom, opts) { calls.push({ action: "setView", center: c, zoom, opts }); here = { lat: c[0], lng: c[1] }; },
      panBy(offset) {
        calls.push({ action: "panBy", offset });
        const p0 = map.latLngToContainerPoint([here.lat, here.lng]);
        const ll = map.containerPointToLatLng({ x: p0.x + offset[0], y: p0.y + offset[1] });
        here = { lat: ll.lat, lng: ll.lng };
      },
      _rawPanBy(offset) {
        calls.push({ action: "panBy", offset });
        const p0 = map.latLngToContainerPoint([here.lat, here.lng]);
        const ll = map.containerPointToLatLng({ x: p0.x + (offset.x ?? 0), y: p0.y + (offset.y ?? 0) });
        here = { lat: ll.lat, lng: ll.lng };
      },
      getSize() { return { x: 1000, y: 800 }; },
      getCenter() { return here; },
      getZoom() { return 5; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : ll.lng;
        return { x: lng * 10, y: lat * 10 };
      },
      containerPointToLatLng(p) { return { lat: p.y / 10, lng: p.x / 10 }; },
      getBoundsZoom() { return 5; },
      getBounds() {
        return {
          getNorth: () => 50,
          getSouth: () => 40,
          getEast: () => 10,
          getWest: () => -10,
        };
      },
    };
    return { map, calls };
  }

  it("borne le pas par la vitesse, et garde le bateau dans 40 % du centre", () => {
    const { map } = fakeMap({ lat: 46, lng: -1 });
    const clamped = clampFilmPan([46, -1], [46, 9], map, { maxFrac: FILM_PAN_MAX_SCREEN, boat: [46, -0.5] });
    const movedPx = Math.abs((clamped[1] - (-1)) * 10);
    assert.ok(movedPx <= 1000 * FILM_BOAT_KEEP_FRAC + 1e-6, `déplacement ${movedPx} px hors cadre`);

    const first = applyFilmCamera(map, {
      chapterIdx: 0,
      lastChapterIdx: 0,
      lat: 46,
      lon: -0.5,
      heading: 90,
      zoom: 5,
      now: 50,
      lastCenter: [46, -1],
      boatPx: 8,
      framesSinceReset: 0,
    });
    assert.ok(first.action === "panBy" || first.action === "setView" || first.action === "hold");
    const step = Math.abs(first.lastCenter[1] - (-1));
    assert.ok(step <= 4 + 1e-6, `lon ${step}° trop grand pour un pas`);
  });

  it("un seul setView au changement de chapitre, hold 1 s, puis translation", () => {
    const { map, calls } = fakeMap();
    const a = applyFilmCamera(map, {
      chapterIdx: 0, lastChapterIdx: null, lat: 46, lon: -1, heading: 0, zoom: 5, now: 0,
    });
    const b = applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: a.lastChapterIdx, lat: 40, lon: 8, heading: 0, zoom: 5,
      now: 100, lastSetViewAt: a.lastSetViewAt, flyingUntil: a.flyingUntil, lastCenter: a.lastCenter,
      lastBoat: { lat: 46, lon: -1 },
    });
    assert.equal(b.action, "setView");
    assert.deepEqual(b.lastCenter, [40, 8], "bateau au centre, pas le milieu de jambe");
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
    const viewsAtFlip = calls.filter((c) => c.action === "setView").length;
    let st = b;
    for (let i = 0; i < 8; i++) {
      st = applyFilmCamera(map, {
        chapterIdx: 1, lastChapterIdx: st.lastChapterIdx, lat: 40.01 + i * 0.002, lon: 8.01 + i * 0.002,
        heading: 0, zoom: 5,
        now: 200 + i * 16, lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter, framesSinceReset: st.framesSinceReset, boatPx: 6,
        stillAnchor: st.stillAnchor, lastBoat: { lat: 40.01 + i * 0.002, lon: 8.01 + i * 0.002 },
      });
      assert.equal(st.action, "hold", `pan/setView pendant le hold (${st.action} à ${i})`);
    }
    assert.equal(calls.filter((c) => c.action === "setView").length, viewsAtFlip);
    assert.equal(calls.filter((c) => c.action === "panBy").length, 0);
    const afterHold = 100 + FILM_FLIP_HOLD_MS + 16;
    for (let i = 0; i < 8; i++) {
      st = applyFilmCamera(map, {
        chapterIdx: 1, lastChapterIdx: st.lastChapterIdx, lat: 40.05 + i * 0.01, lon: 8.05 + i * 0.01,
        heading: 0, zoom: 5,
        now: afterHold + i * 16, lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter, framesSinceReset: st.framesSinceReset, boatPx: 6,
        stillAnchor: st.stillAnchor, lastBoat: { lat: 40.04 + i * 0.01, lon: 8.04 + i * 0.01 },
      });
      assert.notEqual(st.action, "flyTo");
    }
    assert.ok(calls.filter((c) => c.action === "panBy").length >= 1, "pas de translation après le hold");
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
  });
});

describe("filmCamera — dézoom archipels, tuiles gardées", () => {
  it("plafonne le zoom pour une jambe à sauts courts", () => {
    const map = {
      getBoundsZoom() { return 8; },
      getSize() { return { x: 1280, y: 800 }; },
    };
    const hop = { fromLat: 14.6, fromLon: -61.07, toLat: 16.25, toLon: -61.53 };
    const z = filmChapterZoom(map, hop);
    assert.ok(z <= FILM_ZOOM_ARCHIPELAGO_MAX, `zoom archipel ${z} > ${FILM_ZOOM_ARCHIPELAGO_MAX}`);
    assert.ok(z >= 3);

    const ocean = { fromLat: 41.92, fromLon: 8.74, toLat: 14.6, toLon: -61.07 };
    const zOcean = filmChapterZoom(map, ocean);
    assert.ok(zOcean <= 7);
    assert.ok(z < zOcean || z <= FILM_ZOOM_ARCHIPELAGO_MAX);
  });

  it("pas de switch de base layer pendant filmActive", () => {
    assert.match(controller, /switchBaseLayer\(/);
    assert.match(controller, /if \(this\.config\.filmActive\)/);
    assert.match(controller, /if \(!this\.baseLayer\) this\.switchBaseLayer\(url, attr\)/);
    assert.match(controller, /next\.addTo\(this\.map\)/);
    assert.match(controller, /if \(prev && prev !== next\) prev\.remove\(\)/);
    assert.match(controller, /exitHoldZoom/);
    assert.doesNotMatch(controller, /filmActive[\s\S]{0,80}fitBounds/);
    assert.doesNotMatch(controller, /filmActive[\s\S]{0,200}zoomForRemaining/);
  });
});

describe("filmCamera — interpolation hors React, zoom figé, tuiles", () => {
  function fakeMap(center = { lat: 46, lng: -1 }) {
    const calls = [];
    let here = { ...center };
    const map = {
      flyTo(c, zoom) { calls.push({ action: "flyTo", center: c, zoom }); here = { lat: c[0], lng: c[1] }; },
      setView(c, zoom, opts) { calls.push({ action: "setView", center: c, zoom, opts }); here = { lat: c[0], lng: c[1] }; },
      panBy(offset) {
        calls.push({ action: "panBy", offset });
        const p0 = map.latLngToContainerPoint([here.lat, here.lng]);
        const ll = map.containerPointToLatLng({ x: p0.x + offset[0], y: p0.y + offset[1] });
        here = { lat: ll.lat, lng: ll.lng };
      },
      _rawPanBy(offset) {
        calls.push({ action: "panBy", offset });
        const p0 = map.latLngToContainerPoint([here.lat, here.lng]);
        const ll = map.containerPointToLatLng({ x: p0.x + (offset.x ?? 0), y: p0.y + (offset.y ?? 0) });
        here = { lat: ll.lat, lng: ll.lng };
      },
      getSize() { return { x: 1000, y: 800 }; },
      getCenter() { return here; },
      getZoom() { return 5; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : ll.lng;
        return { x: lng * 10, y: lat * 10 };
      },
      containerPointToLatLng(p) { return { lat: p.y / 10, lng: p.x / 10 }; },
      getBoundsZoom() { return 5; },
      getBounds() {
        return {
          getNorth: () => 50,
          getSouth: () => 40,
          getEast: () => 10,
          getWest: () => -10,
        };
      },
    };
    return { map, calls };
  }

  it("cadence dégradée : positions caméra monotones, pas au-delà du pas borné", () => {
    const { map } = fakeMap({ lat: 46, lng: -1 });
    const samples = [];
    for (let i = 0; i <= 5; i++) {
      pushFilmSample(samples, {
        t: i * 200,
        lat: 46,
        lon: -1 + i * 2,
        heading: 90,
        chapterIdx: 0,
      });
    }
    let lastChapterIdx = 0;
    let lastCenter = [46, -1];
    let flyingUntil = 0;
    let framesSinceReset = 0;
    let lastBoat = { lat: 46, lon: -1 };
    const centers = [];
    const actions = [];
    const maxPx = 1000 * FILM_BOAT_KEEP_FRAC + 1e-6;
    for (let now = FILM_INTERP_DELAY_MS; now <= 1000; now += 16) {
      const next = stepFilmCamera(map, {
        samples,
        now,
        lastChapterIdx,
        lastCenter,
        flyingUntil,
        zoom: 5,
        tilesReady: true,
        chapterIdx: 0,
        lastBoat,
        framesSinceReset,
      });
      lastChapterIdx = next.lastChapterIdx;
      lastCenter = next.lastCenter;
      flyingUntil = next.flyingUntil;
      framesSinceReset = next.framesSinceReset || 0;
      if (next.pose) lastBoat = { lat: next.pose.lat, lon: next.pose.lon };
      actions.push(next.action);
      if ((next.action === "setView" || next.action === "panBy") && lastCenter) centers.push(lastCenter);
    }
    assert.ok(centers.length >= 8, `pas assez de pas (${centers.length})`);
    assert.ok(actions.filter((a) => a === "panBy").length >= 4, `pas assez de panBy (${actions.join(",")})`);
    for (let i = 1; i < centers.length; i++) {
      assert.ok(centers[i][1] >= centers[i - 1][1] - 1e-9, `lon recule à ${i}`);
      const stepPx = Math.abs((centers[i][1] - centers[i - 1][1]) * 10);
      assert.ok(stepPx <= maxPx, `saut ${stepPx} px > ${maxPx} px`);
    }
    assert.equal(filmPanMaxFrac(false), FILM_PAN_MAX_SCREEN * FILM_TILE_SLOW);
  });

  it("zoom de croisière stable au milieu de jambe (hors approche)", () => {
    const { map, calls } = fakeMap();
    const samples = [];
    pushFilmSample(samples, { t: 0, lat: 46, lon: -1, heading: 90, chapterIdx: 0 });
    pushFilmSample(samples, { t: 400, lat: 46.2, lon: 0, heading: 90, chapterIdx: 0 });
    let st = { lastChapterIdx: 0, lastCenter: [46, -1], flyingUntil: 0, framesSinceReset: 0 };
    for (let now = 80; now <= 400; now += 16) {
      const next = stepFilmCamera(map, {
        samples,
        now,
        ...st,
        zoom: 5,
        baseZoom: 5,
        chapterIdx: 0,
      });
      st = {
        lastChapterIdx: next.lastChapterIdx,
        lastCenter: next.lastCenter,
        flyingUntil: next.flyingUntil,
        framesSinceReset: next.framesSinceReset || 0,
      };
    }
    const zooms = calls.filter((c) => c.action === "setView").map((c) => c.zoom);
    assert.ok(zooms.every((z) => z == null || Math.abs(z - 5) < 0.4), `zoom ${zooms.join(",")}`);
  });

  it("interpole entre deux échantillons espacés", () => {
    const samples = [];
    pushFilmSample(samples, { t: 0, lat: 46, lon: -1, heading: 90, chapterIdx: 0, filmNm: 0 });
    pushFilmSample(samples, { t: 200, lat: 46, lon: 1, heading: 90, chapterIdx: 0, filmNm: 10 });
    const mid = interpolateFilmSamples(samples, 100);
    assert.ok(Math.abs(mid.lon - 0) < 1e-9, `lon milieu ${mid.lon}`);
    assert.ok(Math.abs(mid.filmNm - 5) < 1e-9);
  });

  it("ne lisse pas un flip de chapitre (Ajaccio → Fort-de-France)", () => {
    const samples = [];
    pushFilmSample(samples, { t: 0, lat: 41.9192, lon: 8.7386, heading: 250, chapterIdx: 4 });
    pushFilmSample(samples, { t: 80, lat: 14.6036, lon: -61.0668, heading: 280, chapterIdx: 5 });
    const mid = interpolateFilmSamples(samples, 40);
    assert.ok(Math.abs(mid.lat - 41.9192) < 1e-9, `lerp transat lat ${mid.lat}`);
    assert.equal(mid.chapterIdx, 4);
    const after = interpolateFilmSamples(samples, 80);
    assert.ok(Math.abs(after.lat - 14.6036) < 1e-9, `snap FDF lat ${after.lat}`);
    assert.equal(after.chapterIdx, 5);
  });

  it("ne lisse pas un téléport transat dans le même chapitre", () => {
    const samples = [];
    pushFilmSample(samples, { t: 0, lat: 41.9192, lon: 8.7386, heading: 250, chapterIdx: 5 });
    pushFilmSample(samples, { t: 80, lat: 14.6036, lon: -61.0668, heading: 280, chapterIdx: 5 });
    const mid = interpolateFilmSamples(samples, 40);
    assert.ok(Math.abs(mid.lat - 41.9192) < 1e-9, `lerp transat même ch lat ${mid.lat}`);
  });

  it("précharge les tuiles d'une jambe au zoom du chapitre", () => {
    const tiles = tilesAlongLeg({ fromLat: 46, fromLon: -1, toLat: 46.2, toLon: 0 }, 5);
    assert.ok(tiles.length > 0);
    assert.ok(tiles.every((t) => t.z === 5));
    const urls = [];
    class FakeImage {
      set src(v) { urls.push(v); }
    }
    preloadFilmTiles("http://t/{z}/{y}/{x}", tiles.slice(0, 3), { ImageCtor: FakeImage });
    assert.equal(urls.length, 3);
    assert.match(urls[0], /\/5\//);
  });

  it("MapSceneController : boucle rAF hors du rendu React", () => {
    assert.match(controller, /ensureFilmCameraLoop/);
    assert.match(controller, /requestAnimationFrame\(tick\)/);
    assert.match(controller, /stepFilmCamera/);
    assert.match(controller, /preloadFilmTiles/);
    assert.doesNotMatch(controller, /if \(this\.config\.filmActive\) this\.syncFilmCamera\(this\.config\);/);
  });
});

describe("filmCamera — 60 Hz, cap lissé, zoom d'approche", () => {
  it("ne pose pas de setView à chaque frame : translation puis commit", () => {
    const calls = [];
    let here = { lat: 46, lng: -1 };
    const map = {
      flyTo() { calls.push("flyTo"); },
      setView(c) { calls.push("setView"); here = { lat: c[0], lng: c[1] }; },
      _rawPanBy() { calls.push("panBy"); },
      panBy() { calls.push("panBy"); },
      getSize() { return { x: 1000, y: 800 }; },
      getCenter() { return here; },
      getZoom() { return 5; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : ll.lng;
        return { x: lng * 10, y: lat * 10 };
      },
      containerPointToLatLng(p) { return { lat: p.y / 10, lng: p.x / 10 }; },
    };
    applyFilmCamera(map, {
      chapterIdx: 0, lastChapterIdx: null, lat: 46, lon: -1, heading: 90, zoom: 5, now: 0,
    });
    let lastCenter = [46, -1];
    let framesSinceReset = 0;
    for (let i = 1; i <= 12; i++) {
      const next = applyFilmCamera(map, {
        chapterIdx: 0, lastChapterIdx: 0, lat: 46, lon: -1 + i * 0.05, heading: 90, zoom: 5,
        now: i * 16, lastCenter, framesSinceReset, boatPx: 5,
      });
      lastCenter = next.lastCenter;
      framesSinceReset = next.framesSinceReset;
    }
    const views = calls.filter((c) => c === "setView").length;
    const pans = calls.filter((c) => c === "panBy").length;
    assert.ok(pans >= 6, `panBy ${pans}`);
    assert.ok(views <= 3, `setView trop fréquent : ${views}`);
    assert.equal(calls.filter((c) => c === "flyTo").length, 0);
  });

  it("lisse le cap sur la jambe, pas le cap instantané", () => {
    const samples = [];
    pushFilmSample(samples, { t: 0, lat: 46, lon: -1, heading: 80, chapterIdx: 0 });
    pushFilmSample(samples, { t: 80, lat: 46, lon: -0.8, heading: 90, chapterIdx: 0 });
    pushFilmSample(samples, { t: 160, lat: 46, lon: -0.6, heading: 100, chapterIdx: 0 });
    const h = smoothFilmHeading(samples, 160);
    assert.ok(Math.abs(h - 90) < 8, `cap lissé ${h} trop près de l'instantané 160`);
    assert.ok(h > 80 && h < 120);
  });

  it("resserre le zoom à l'approche et l'élargit au départ", () => {
    const mid = filmApproachZoom(5, 0.5);
    const start = filmApproachZoom(5, 0);
    const end = filmApproachZoom(5, 1);
    assert.ok(start < mid, `départ ${start} n'est pas plus large que ${mid}`);
    assert.ok(end > mid, `approche ${end} n'est pas plus serrée que ${mid}`);
    assert.equal(mid, 5);
  });

  it("keepBoatInFrame ramène un bateau trop loin du centre", () => {
    const map = {
      getSize() { return { x: 1000, y: 800 }; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : ll.lng;
        return { x: 500 + lng * 20, y: 400 - lat };
      },
      containerPointToLatLng(p) { return { lat: 400 - p.y, lng: (p.x - 500) / 20 }; },
    };
    const kept = keepBoatInFrame([0, 0], [0, 20], map);
    const boat = map.latLngToContainerPoint([0, 20]);
    const center = map.latLngToContainerPoint(kept);
    const dx = Math.abs(boat.x - center.x);
    assert.ok(dx <= 1000 * FILM_BOAT_KEEP_FRAC * 0.5 + 1, `bateau à ${dx} px du centre`);
  });

  it("MapSceneController : sillage à la frame et bateau posé pendant le film", () => {
    assert.match(controller, /this\.renderDynamic\(this\.currentPlayback \|\| this\.playback\.snapshot\(\)\)/);
    assert.match(controller, /if \(this\.zoomAnimating && markers\.length\) return/);
    assert.doesNotMatch(controller, /zoomAnimating && markers\.length && !this\.config\.filmActive/);
    assert.match(controller, /stabilizeWorldLng\(subject\.lon/);
    assert.match(controller, /filmActive: this\.config\.filmActive/);
    assert.match(controller, /filmFramesSinceReset/);
  });
});

describe("filmCamera — chapitre sans bond (Δnm≈0, zoom 6→4)", () => {
  function mercatorMap(center = { lat: 46.1541, lng: -1.167 }, zoom = 6) {
    const size = { x: 1280, y: 800 };
    let here = { ...center };
    let z = zoom;
    const calls = [];
    function project(lat, lng, zoomLevel = z) {
      const scale = 256 * (2 ** zoomLevel);
      const x = ((lng + 180) / 360) * scale;
      const sin = Math.sin((lat * Math.PI) / 180);
      const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
      return { x, y };
    }
    const map = {
      flyTo() { calls.push({ action: "flyTo" }); },
      setView(c, nextZoom, opts) {
        calls.push({ action: "setView", center: c, zoom: nextZoom, opts });
        here = { lat: c[0], lng: c[1] };
        if (Number.isFinite(Number(nextZoom))) z = Number(nextZoom);
      },
      panBy() { calls.push({ action: "panBy" }); },
      _rawPanBy() { calls.push({ action: "panBy" }); },
      getSize() { return size; },
      getCenter() { return here; },
      getZoom() { return z; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : (ll.lng ?? ll.lon);
        const p = project(lat, lng);
        const c = project(here.lat, here.lng);
        return { x: size.x / 2 + (p.x - c.x), y: size.y / 2 + (p.y - c.y) };
      },
      containerPointToLatLng(p) {
        const c = project(here.lat, here.lng);
        const scale = 256 * (2 ** z);
        const wx = c.x + (p.x - size.x / 2);
        const wy = c.y + (p.y - size.y / 2);
        const lng = (wx / scale) * 360 - 180;
        const n = Math.PI - ((2 * Math.PI * wy) / scale);
        const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
        return { lat, lng };
      },
      getBounds() {
        const nw = map.containerPointToLatLng({ x: 0, y: 0 });
        const se = map.containerPointToLatLng({ x: size.x, y: size.y });
        return {
          getNorth: () => nw.lat,
          getSouth: () => se.lat,
          getEast: () => se.lng,
          getWest: () => nw.lng,
        };
      },
    };
    const boatPx = (lat, lon) => {
      const p = map.latLngToContainerPoint([lat, lon]);
      return { x: p.x, y: p.y };
    };
    return { map, calls, boatPx };
  }

  it("même lat/lon, chapterIdx 0→1, zoom 6→4 → |Δpx| ≤ 40, au plus un setView", () => {
    const lat = 46.1541;
    const lon = -1.167;
    const { map, calls, boatPx } = mercatorMap({ lat, lng: lon }, 6);
    const first = applyFilmCamera(map, {
      chapterIdx: 0, lastChapterIdx: null, lat, lon, heading: 260, zoom: 6, now: 0,
    });
    const p0 = boatPx(lat, lon);
    const views0 = calls.filter((c) => c.action === "setView").length;
    const flip = applyFilmCamera(map, {
      chapterIdx: 1,
      lastChapterIdx: first.lastChapterIdx,
      lat,
      lon,
      heading: 140,
      zoom: 4,
      now: 100,
      lastSetViewAt: first.lastSetViewAt,
      lastCenter: first.lastCenter,
      lastBoat: { lat, lon },
      stillAnchor: first.stillAnchor,
    });
    const p1 = boatPx(lat, lon);
    const dpx = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    assert.ok(dpx <= 40, `bond au flip ${dpx.toFixed(1)} px`);
    const views1 = calls.filter((c) => c.action === "setView").length;
    assert.ok(views1 - views0 <= 1, `setView au flip : ${views1 - views0}`);
    assert.notEqual(flip.action, "flyTo");
    assert.ok(flip.action === "hold" || flip.action === "setView" || flip.action === "panBy");

    let st = flip;
    let prev = p1;
    const extraViews = [];
    for (let i = 0; i < 8; i++) {
      const viewsBefore = calls.filter((c) => c.action === "setView").length;
      st = applyFilmCamera(map, {
        chapterIdx: 1,
        lastChapterIdx: st.lastChapterIdx,
        lat,
        lon,
        heading: 140,
        zoom: 4,
        now: 200 + i * 16,
        lastSetViewAt: st.lastSetViewAt,
        lastCenter: st.lastCenter,
        lastBoat: { lat, lon },
        framesSinceReset: st.framesSinceReset,
        boatPx: 0,
        stillAnchor: st.stillAnchor,
      });
      const p = boatPx(lat, lon);
      const d = Math.hypot(p.x - prev.x, p.y - prev.y);
      assert.ok(d <= 40, `saut ${i + 2} : ${d.toFixed(1)} px`);
      extraViews.push(calls.filter((c) => c.action === "setView").length - viewsBefore);
      prev = p;
    }
    const snapped = extraViews.filter((n) => n > 1).length;
    assert.equal(snapped, 0, "pas un 2e/3e setView sur la même frame");
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
  });

  it("30 frames après ch0→ch1, même lat/lon, zoom 6→4 : cumul |Δpx| ≤ 40", () => {
    const lat = 46.1541;
    const lon = -1.167;
    const { map, calls, boatPx } = mercatorMap({ lat, lng: lon }, 6);
    const first = applyFilmCamera(map, {
      chapterIdx: 0, lastChapterIdx: null, lat, lon, heading: 260, zoom: 6, now: 0,
    });
    const pBefore = boatPx(lat, lon);
    const flip = applyFilmCamera(map, {
      chapterIdx: 1,
      lastChapterIdx: first.lastChapterIdx,
      lat,
      lon,
      heading: 140,
      zoom: 4,
      now: 100,
      lastSetViewAt: first.lastSetViewAt,
      lastCenter: first.lastCenter,
      lastBoat: { lat, lon },
      stillAnchor: first.stillAnchor,
    });
    let st = flip;
    for (let i = 0; i < 30; i++) {
      st = applyFilmCamera(map, {
        chapterIdx: 1,
        lastChapterIdx: st.lastChapterIdx,
        lat,
        lon,
        heading: 140,
        zoom: 4,
        now: 200 + i * 16,
        lastSetViewAt: st.lastSetViewAt,
        lastCenter: st.lastCenter,
        lastBoat: { lat, lon },
        framesSinceReset: st.framesSinceReset,
        boatPx: 0,
        stillAnchor: st.stillAnchor,
      });
    }
    const pFinal = boatPx(lat, lon);
    const total = Math.hypot(pFinal.x - pBefore.x, pFinal.y - pBefore.y);
    assert.ok(total <= 40, `cumul après flip ${total.toFixed(1)} px (seuil 40)`);
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
    assert.match(controller, /filmStillAnchor/);
  });

  it("stepFilmCamera : zoom courant gardé, la nouvelle jambe est visée par pas", () => {
    const lat = 46.1541;
    const lon = -1.167;
    const { map, boatPx } = mercatorMap({ lat, lng: lon }, 6);
    const samples = [];
    pushFilmSample(samples, { t: 0, lat, lon, heading: 260, chapterIdx: 0 });
    pushFilmSample(samples, { t: 200, lat, lon, heading: 140, chapterIdx: 1 });
    const a = stepFilmCamera(map, {
      samples, now: 80, lastChapterIdx: null, zoom: 6, baseZoom: 6, chapterIdx: 0,
    });
    const p0 = boatPx(lat, lon);
    const b = stepFilmCamera(map, {
      samples,
      now: 280,
      lastChapterIdx: a.lastChapterIdx,
      lastCenter: a.lastCenter,
      lastSetViewAt: a.lastSetViewAt,
      zoom: 6,
      baseZoom: 4,
      chapterIdx: 1,
      lastBoat: { lat, lon },
      framesSinceReset: a.framesSinceReset,
      stillAnchor: a.stillAnchor,
    });
    const p1 = boatPx(lat, lon);
    const dpx = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    assert.ok(dpx <= 40, `bond stepFilmCamera ${dpx.toFixed(1)} px`);
    assert.ok(Number(b.zoom) >= 5.8, `zoom snappé ${b.zoom}, attendu ~5.92`);
    assert.ok(Number(b.zoom) <= 6.01);
    assert.match(controller, /if \(this\.camera\.filmZoom == null\) this\.camera\.filmZoom = this\.camera\.filmZoomBase/);
  });
});

describe("filmCamera — pleine jambe, pas de saut d'ancre", () => {
  function mercatorMap(center = { lat: 14.6, lng: -61.07 }, zoom = 6.75) {
    const size = { x: 1280, y: 800 };
    let here = { ...center };
    let z = zoom;
    const calls = [];
    function project(lat, lng, zoomLevel = z) {
      const scale = 256 * (2 ** zoomLevel);
      const x = ((lng + 180) / 360) * scale;
      const sin = Math.sin((lat * Math.PI) / 180);
      const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
      return { x, y };
    }
    const map = {
      flyTo() { calls.push({ action: "flyTo" }); },
      setView(c, nextZoom, opts) {
        calls.push({ action: "setView", center: c, zoom: nextZoom, opts });
        here = { lat: c[0], lng: c[1] };
        if (Number.isFinite(Number(nextZoom))) z = Number(nextZoom);
      },
      panBy() { calls.push({ action: "panBy" }); },
      _rawPanBy() { calls.push({ action: "panBy" }); },
      getSize() { return size; },
      getCenter() { return here; },
      getZoom() { return z; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : (ll.lng ?? ll.lon);
        const p = project(lat, lng);
        const c = project(here.lat, here.lng);
        return { x: size.x / 2 + (p.x - c.x), y: size.y / 2 + (p.y - c.y) };
      },
      containerPointToLatLng(p) {
        const c = project(here.lat, here.lng);
        const scale = 256 * (2 ** z);
        const wx = c.x + (p.x - size.x / 2);
        const wy = c.y + (p.y - size.y / 2);
        const lng = (wx / scale) * 360 - 180;
        const n = Math.PI - ((2 * Math.PI * wy) / scale);
        const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
        return { lat, lng };
      },
      getBounds() {
        const nw = map.containerPointToLatLng({ x: 0, y: 0 });
        const se = map.containerPointToLatLng({ x: size.x, y: size.y });
        return {
          getNorth: () => nw.lat,
          getSouth: () => se.lat,
          getEast: () => se.lng,
          getWest: () => nw.lng,
        };
      },
    };
    const centerPx = () => map.latLngToContainerPoint([here.lat, here.lng]);
    return { map, calls, centerPx };
  }

  const FDF = [14.6036, -61.0668];
  const GUADELOUPE = [16.241, -61.533];
  const MARIGOT = [18.0731, -63.0822];
  const CARAIBE = {
    fromLat: FDF[0], fromLon: FDF[1], toLat: MARIGOT[0], toLon: MARIGOT[1],
  };

  it("Fort-de-France → Marigot est un archipel (un cadre pour le chapitre)", () => {
    assert.ok(filmLegIsArchipelago(CARAIBE), "jambe Caraïbes hors seuil archipel");
    assert.ok(FILM_ARCHIPELAGO_NM >= 238);
    const mid = filmChapterCenter(CARAIBE);
    assert.ok(mid);
    assert.ok(Math.abs(mid[0] - (FDF[0] + MARIGOT[0]) / 2) < 1e-9);
  });

  it("Caraïbes : île en île, même chapterIdx, centre < 80 px en 1 s", () => {
    const hops = [FDF, GUADELOUPE, MARIGOT];
    const { map, calls, centerPx } = mercatorMap({ lat: FDF[0], lng: FDF[1] }, 6.75);
    let st = applyFilmCamera(map, {
      chapterIdx: 7, lastChapterIdx: null, lat: FDF[0], lon: FDF[1],
      heading: 310, zoom: 6.75, now: 0, filmLeg: CARAIBE,
    });
    const p0 = centerPx();
    let prev = { lat: FDF[0], lon: FDF[1] };
    for (let i = 0; i < 60; i++) {
      const hop = i < 20 ? 0 : i < 40 ? 1 : 2;
      const [lat, lon] = hops[hop];
      st = applyFilmCamera(map, {
        chapterIdx: 7,
        lastChapterIdx: 7,
        lat,
        lon,
        heading: 310 + hop * 8,
        zoom: 6.75,
        now: 16 * (i + 1),
        lastCenter: st.lastCenter,
        lastBoat: prev,
        framesSinceReset: st.framesSinceReset,
        stillAnchor: null,
        filmLeg: CARAIBE,
      });
      prev = { lat, lon };
    }
    const p1 = centerPx();
    const dpx = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    assert.ok(dpx < 80, `centre Caraïbes ${dpx.toFixed(1)} px en 1 s`);
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
  });

  it("ancre (bouée / Sardaigne) : le centre ne saute pas avec le bateau", () => {
    const { map, centerPx } = mercatorMap({ lat: 41.2, lng: 9.4 }, 6.75);
    const first = applyFilmCamera(map, {
      chapterIdx: 2, lastChapterIdx: null, lat: 41.2, lon: 9.4,
      heading: 140, zoom: 6.75, now: 0,
    });
    let st = applyFilmCamera(map, {
      chapterIdx: 2, lastChapterIdx: 2, lat: 41.21, lon: 9.41,
      heading: 140, zoom: 6.75, now: 16,
      lastCenter: first.lastCenter, lastBoat: { lat: 41.2, lon: 9.4 },
      framesSinceReset: first.framesSinceReset,
    });
    const p0 = centerPx();
    st = applyFilmCamera(map, {
      chapterIdx: 2, lastChapterIdx: 2, lat: 39.2, lon: 9.1,
      heading: 200, zoom: 6.75, now: 32,
      lastCenter: st.lastCenter, lastBoat: { lat: 41.21, lon: 9.41 },
      framesSinceReset: st.framesSinceReset,
    });
    const p1 = centerPx();
    const dpx = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    assert.ok(dpx < 80, `saut d'ancre ${dpx.toFixed(1)} px`);
  });

  it("pleine mer : la caméra traduit avec le bateau (pas figée)", () => {
    const { map } = mercatorMap({ lat: 46.15, lng: -1.17 }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: null, lat: 46.15, lon: -1.17,
      heading: 140, zoom: 5, now: 0,
    });
    let st = first;
    let prev = { lat: 46.15, lon: -1.17 };
    for (let i = 1; i <= 24; i++) {
      const lat = 46.15 - i * 0.02;
      const lon = -1.17 + i * 0.03;
      st = applyFilmCamera(map, {
        chapterIdx: 1, lastChapterIdx: 1, lat, lon, heading: 140, zoom: 5,
        now: i * 16, lastCenter: st.lastCenter, lastBoat: prev,
        framesSinceReset: st.framesSinceReset, boatPx: 8,
      });
      prev = { lat, lon };
    }
    const dLat = Math.abs(st.lastCenter[0] - 46.15);
    const dLon = Math.abs(st.lastCenter[1] - (-1.17));
    assert.ok(dLat + dLon > 0.05, "caméra figée en pleine mer");
  });

  it("filmIntraChapterCenter : glisse avec le bateau, pas de saut", () => {
    const { map } = mercatorMap({ lat: FDF[0], lng: FDF[1] }, 6.75);
    const pap = GUADELOUPE;
    const n = 24;
    let center = FDF;
    let lastBoat = { lat: FDF[0], lon: FDF[1] };
    let maxJump = 0;
    for (let i = 1; i <= n; i++) {
      const u = i / n;
      const boat = [
        FDF[0] + (pap[0] - FDF[0]) * u,
        FDF[1] + (pap[1] - FDF[1]) * u,
      ];
      const next = filmIntraChapterCenter(map, {
        from: center, boat, lastBoat, filmLeg: CARAIBE,
      });
      maxJump = Math.max(maxJump, Math.hypot(next[0] - center[0], next[1] - center[1]));
      center = next;
      lastBoat = { lat: boat[0], lon: boat[1] };
    }
    const moved = Math.abs(center[0] - FDF[0]) + Math.abs(center[1] - FDF[1]);
    assert.ok(moved > 0.05, "caméra figée sur Fort-de-France → Pointe-à-Pitre");
    assert.ok(maxJump <= 0.4, `saut ${maxJump.toFixed(3)}°`);
  });

  it("hop FDF → PAP, N frames : le centre glisse, aucun saut > 0,4°, stillAnchor lâché", () => {
    const pap = GUADELOUPE;
    const { map, calls } = mercatorMap({ lat: FDF[0], lng: FDF[1] }, 6.75);
    let st = applyFilmCamera(map, {
      chapterIdx: 6, lastChapterIdx: null, lat: FDF[0], lon: FDF[1],
      heading: 310, zoom: 6.75, now: 0, filmLeg: CARAIBE,
    });
    const views0 = calls.filter((c) => c.action === "setView").length;
    let prev = { lat: FDF[0], lon: FDF[1] };
    let maxJump = 0;
    const n = 24;
    for (let i = 1; i <= n; i++) {
      const u = i / n;
      const lat = FDF[0] + (pap[0] - FDF[0]) * u;
      const lon = FDF[1] + (pap[1] - FDF[1]) * u;
      const before = st.lastCenter;
      st = applyFilmCamera(map, {
        chapterIdx: 6, lastChapterIdx: 6, lat, lon, heading: 310, zoom: 6.75,
        now: i * 16, lastCenter: st.lastCenter, lastBoat: prev,
        framesSinceReset: st.framesSinceReset, stillAnchor: st.stillAnchor,
        filmLeg: CARAIBE, boatPx: 8,
      });
      maxJump = Math.max(
        maxJump,
        Math.hypot(st.lastCenter[0] - before[0], st.lastCenter[1] - before[1]),
      );
      prev = { lat, lon };
    }
    const dLat = Math.abs(st.lastCenter[0] - FDF[0]);
    const dLon = Math.abs(st.lastCenter[1] - FDF[1]);
    assert.ok(dLat + dLon > 0.05, "caméra figée sur Fort-de-France → Pointe-à-Pitre");
    assert.ok(maxJump <= 0.4, `saut ${maxJump.toFixed(3)}°`);
    assert.equal(st.stillAnchor, null, "stillAnchor encore sur le point de flip");
    const views1 = calls.filter((c) => c.action === "setView").length;
    assert.ok(views1 - views0 <= 1, `setView île en île : ${views1 - views0}`);
  });
});

describe("filmCamera — un mouvement au flip, bateau au centre", () => {
  function mercatorMap(center = { lat: 41.9192, lng: 8.7386 }, zoom = 5) {
    const size = { x: 1280, y: 800 };
    let here = { ...center };
    let z = zoom;
    const calls = [];
    function project(lat, lng, zoomLevel = z) {
      const scale = 256 * (2 ** zoomLevel);
      const x = ((lng + 180) / 360) * scale;
      const sin = Math.sin((lat * Math.PI) / 180);
      const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
      return { x, y };
    }
    const map = {
      flyTo() { calls.push({ action: "flyTo" }); },
      setView(c, nextZoom, opts) {
        calls.push({ action: "setView", center: c, zoom: nextZoom, opts });
        here = { lat: c[0], lng: c[1] };
        if (Number.isFinite(Number(nextZoom))) z = Number(nextZoom);
      },
      panBy(offset) { calls.push({ action: "panBy", offset }); },
      _rawPanBy(offset) { calls.push({ action: "panBy", offset }); },
      getSize() { return size; },
      getCenter() { return here; },
      getZoom() { return z; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : (ll.lng ?? ll.lon);
        const p = project(lat, lng);
        const c = project(here.lat, here.lng);
        return { x: size.x / 2 + (p.x - c.x), y: size.y / 2 + (p.y - c.y) };
      },
      containerPointToLatLng(p) {
        const c = project(here.lat, here.lng);
        const scale = 256 * (2 ** z);
        const wx = c.x + (p.x - size.x / 2);
        const wy = c.y + (p.y - size.y / 2);
        const lng = (wx / scale) * 360 - 180;
        const n = Math.PI - ((2 * Math.PI * wy) / scale);
        const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
        return { lat, lng };
      },
      getBounds() {
        const nw = map.containerPointToLatLng({ x: 0, y: 0 });
        const se = map.containerPointToLatLng({ x: size.x, y: size.y });
        return {
          getNorth: () => nw.lat,
          getSouth: () => se.lat,
          getEast: () => se.lng,
          getWest: () => nw.lng,
        };
      },
    };
    const boatPx = (lat, lon) => map.latLngToContainerPoint([lat, lon]);
    return { map, calls, boatPx, size };
  }

  const AJACCIO = [41.9192, 8.7386];
  const FDF = [14.6036, -61.0668];
  const PAP = [16.241, -61.533];
  const TRANSAT = {
    fromLat: AJACCIO[0], fromLon: AJACCIO[1], toLat: FDF[0], toLon: FDF[1],
  };
  const CARAIBE = {
    fromLat: FDF[0], fromLon: FDF[1], toLat: PAP[0], toLon: PAP[1],
  };

  function inCentral40(map, lat, lon, size) {
    const p = map.latLngToContainerPoint([lat, lon]);
    const dx = Math.abs(p.x - size.x / 2) / size.x;
    const dy = Math.abs(p.y - size.y / 2) / size.y;
    return dx <= 0.2 && dy <= 0.2;
  }

  it("flip transat : un setView, bateau au centre, pas le milieu de jambe", () => {
    const { map, calls, boatPx, size } = mercatorMap({ lat: AJACCIO[0], lng: AJACCIO[1] }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 4, lastChapterIdx: null, lat: AJACCIO[0], lon: AJACCIO[1],
      heading: 250, zoom: 5, now: 0, filmLeg: TRANSAT,
    });
    const views0 = calls.filter((c) => c.action === "setView").length;
    const flip = applyFilmCamera(map, {
      chapterIdx: 5,
      lastChapterIdx: first.lastChapterIdx,
      lat: FDF[0],
      lon: FDF[1],
      heading: 280,
      zoom: 5,
      now: 100,
      lastSetViewAt: first.lastSetViewAt,
      lastCenter: first.lastCenter,
      lastBoat: { lat: AJACCIO[0], lon: AJACCIO[1] },
      stillAnchor: first.stillAnchor,
      filmLeg: TRANSAT,
    });
    assert.equal(flip.action, "setView");
    const views1 = calls.filter((c) => c.action === "setView").length;
    assert.equal(views1 - views0, 1, `setView au flip transat : ${views1 - views0}`);
    assert.deepEqual(flip.lastCenter, FDF);
    const mid = filmChapterCenter(TRANSAT);
    assert.ok(Math.hypot(flip.lastCenter[0] - mid[0], flip.lastCenter[1] - mid[1]) > 5,
      "centre = milieu de jambe (bateau encore à l'origine hors cadre)");
    const p = boatPx(FDF[0], FDF[1]);
    assert.ok(inCentral40(map, FDF[0], FDF[1], size), `bateau (${p.x.toFixed(0)},${p.y.toFixed(0)}) hors 40 %`);
    assert.ok(flip.flyingUntil > 100);
    assert.ok(flip.stillAnchor);
  });

  it("après le flip transat : pas de panBy/setView pendant 1 s, FILM_RESET_EVERY ne fait pas (0,0)", () => {
    const { map, calls } = mercatorMap({ lat: AJACCIO[0], lng: AJACCIO[1] }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 4, lastChapterIdx: null, lat: AJACCIO[0], lon: AJACCIO[1],
      heading: 250, zoom: 5, now: 0, filmLeg: TRANSAT,
    });
    let st = applyFilmCamera(map, {
      chapterIdx: 5, lastChapterIdx: first.lastChapterIdx, lat: FDF[0], lon: FDF[1],
      heading: 280, zoom: 5, now: 100,
      lastSetViewAt: first.lastSetViewAt, lastCenter: first.lastCenter,
      lastBoat: { lat: AJACCIO[0], lon: AJACCIO[1] }, stillAnchor: first.stillAnchor,
      filmLeg: TRANSAT,
    });
    const viewsAtFlip = calls.filter((c) => c.action === "setView").length;
    const pansAtFlip = calls.filter((c) => c.action === "panBy").length;
    for (let i = 0; i < 60; i++) {
      const now = 116 + i * 16;
      st = applyFilmCamera(map, {
        chapterIdx: 5, lastChapterIdx: st.lastChapterIdx, lat: FDF[0], lon: FDF[1],
        heading: 280, zoom: 5, now,
        lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter, lastBoat: { lat: FDF[0], lon: FDF[1] },
        framesSinceReset: st.framesSinceReset, stillAnchor: st.stillAnchor,
        filmLeg: TRANSAT, boatPx: 0, idle: true,
      });
      assert.equal(st.action, "hold", `mouvement à t=${now} : ${st.action}`);
      const lastPan = calls.filter((c) => c.action === "panBy").at(-1);
      if (lastPan?.offset) {
        const dx = lastPan.offset.x ?? lastPan.offset[0] ?? 0;
        const dy = lastPan.offset.y ?? lastPan.offset[1] ?? 0;
        assert.ok(Math.hypot(dx, dy) > 0.05 || calls.filter((c) => c.action === "panBy").length === pansAtFlip,
          `panBy (${dx},${dy}) pendant le hold`);
      }
    }
    assert.equal(calls.filter((c) => c.action === "setView").length, viewsAtFlip);
    assert.equal(calls.filter((c) => c.action === "panBy").length, pansAtFlip);
  });

  it("hop Caraïbes après le transat : au plus un setView, bateau au centre", () => {
    const { map, calls, boatPx, size } = mercatorMap({ lat: FDF[0], lng: FDF[1] }, 5);
    const atFdf = applyFilmCamera(map, {
      chapterIdx: 5, lastChapterIdx: null, lat: FDF[0], lon: FDF[1],
      heading: 280, zoom: 5, now: 0, filmLeg: TRANSAT,
    });
    const hop = applyFilmCamera(map, {
      chapterIdx: 6, lastChapterIdx: atFdf.lastChapterIdx,
      lat: FDF[0], lon: FDF[1], heading: 310, zoom: 5, now: 100,
      lastSetViewAt: atFdf.lastSetViewAt, lastCenter: atFdf.lastCenter,
      lastBoat: { lat: FDF[0], lon: FDF[1] }, stillAnchor: atFdf.stillAnchor,
      filmLeg: CARAIBE,
    });
    assert.equal(hop.action, "hold", "Fort-de-France → Pointe-à-Pitre, même lat/lon : hold RC25");
    const views0 = calls.filter((c) => c.action === "setView").length;
    let st = hop;
    st = applyFilmCamera(map, {
      chapterIdx: 6, lastChapterIdx: st.lastChapterIdx,
      lat: PAP[0], lon: PAP[1], heading: 310, zoom: 5,
      now: 100 + FILM_FLIP_HOLD_MS + 16,
      lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
      lastCenter: st.lastCenter, lastBoat: { lat: FDF[0], lon: FDF[1] },
      framesSinceReset: st.framesSinceReset, stillAnchor: st.stillAnchor,
      filmLeg: CARAIBE,
    });
    const views1 = calls.filter((c) => c.action === "setView").length;
    assert.ok(views1 - views0 <= 1, `setView au hop Caraïbes : ${views1 - views0}`);
    const p = boatPx(PAP[0], PAP[1]);
    const dx = Math.abs(p.x - size.x / 2) / size.x;
    const dy = Math.abs(p.y - size.y / 2) / size.y;
    assert.ok(dx <= 0.4 && dy <= 0.4, `bateau hop (${p.x.toFixed(0)},${p.y.toFixed(0)}) hors cadre`);
  });

  it("même chapterIdx, bateau Ajaccio → Fort-de-France : un setView (flip retardé)", () => {
    const { map, calls, boatPx, size } = mercatorMap({ lat: AJACCIO[0], lng: AJACCIO[1] }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 5, lastChapterIdx: null, lat: AJACCIO[0], lon: AJACCIO[1],
      heading: 250, zoom: 5, now: 0, filmLeg: TRANSAT,
    });
    const views0 = calls.filter((c) => c.action === "setView").length;
    const teleport = applyFilmCamera(map, {
      chapterIdx: 5, lastChapterIdx: first.lastChapterIdx,
      lat: FDF[0], lon: FDF[1], heading: 280, zoom: 5, now: 80,
      lastSetViewAt: first.lastSetViewAt, flyingUntil: first.flyingUntil,
      lastCenter: first.lastCenter, lastBoat: { lat: AJACCIO[0], lon: AJACCIO[1] },
      stillAnchor: first.stillAnchor, filmLeg: TRANSAT,
    });
    assert.equal(teleport.action, "setView");
    assert.equal(calls.filter((c) => c.action === "setView").length - views0, 1);
    assert.deepEqual(teleport.lastCenter, FDF);
    const p = boatPx(FDF[0], FDF[1]);
    assert.ok(inCentral40(map, FDF[0], FDF[1], size), `bateau (${p.x.toFixed(0)},${p.y.toFixed(0)}) hors 40 %`);
    let st = teleport;
    const views1 = calls.filter((c) => c.action === "setView").length;
    for (let i = 0; i < 20; i++) {
      st = applyFilmCamera(map, {
        chapterIdx: 5, lastChapterIdx: st.lastChapterIdx, lat: FDF[0], lon: FDF[1],
        heading: 280, zoom: 5, now: 96 + i * 16,
        lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter, lastBoat: { lat: FDF[0], lon: FDF[1] },
        framesSinceReset: st.framesSinceReset, stillAnchor: st.stillAnchor,
        filmLeg: TRANSAT,
      });
      assert.equal(st.action, "hold");
    }
    assert.equal(calls.filter((c) => c.action === "setView").length, views1);
  });

  it("stepFilmCamera : seek transat saute à Fort-de-France, pas un lerp océan", () => {
    const { map, calls, boatPx, size } = mercatorMap({ lat: AJACCIO[0], lng: AJACCIO[1] }, 5);
    const samples = [];
    pushFilmSample(samples, {
      t: 1000, lat: AJACCIO[0], lon: AJACCIO[1], heading: 250, chapterIdx: 4,
    });
    pushFilmSample(samples, {
      t: 1080, lat: FDF[0], lon: FDF[1], heading: 280, chapterIdx: 5,
    });
    const a = stepFilmCamera(map, {
      samples, now: 1080, lastChapterIdx: 4, zoom: 5, baseZoom: 5, chapterIdx: 5,
      lastCenter: AJACCIO, lastBoat: { lat: AJACCIO[0], lon: AJACCIO[1] },
      filmLeg: TRANSAT,
    });
    assert.equal(a.action, "setView");
    assert.ok(Math.abs(a.pose.lat - FDF[0]) < 1e-6, `pose lerp transat ${a.pose.lat}`);
    const p = boatPx(a.pose.lat, a.pose.lon);
    assert.ok(inCentral40(map, a.pose.lat, a.pose.lon, size),
      `bateau step (${p.x.toFixed(0)},${p.y.toFixed(0)}) hors 40 %`);
    const views = calls.filter((c) => c.action === "setView").length;
    assert.equal(views, 1);
  });
});

describe("filmCamera — pas écran ≤ 30 px hors zoom/flip", () => {
  function mercatorMap(center = { lat: 46.1541, lng: -1.167 }, zoom = 5) {
    const size = { x: 1440, y: 860 };
    let here = { ...center };
    let z = zoom;
    const calls = [];
    function project(lat, lng, zoomLevel = z) {
      const scale = 256 * (2 ** zoomLevel);
      const x = ((lng + 180) / 360) * scale;
      const sin = Math.sin((lat * Math.PI) / 180);
      const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
      return { x, y };
    }
    const map = {
      flyTo() { calls.push({ action: "flyTo" }); },
      setView(c, nextZoom, opts) {
        calls.push({ action: "setView", center: c, zoom: nextZoom, opts });
        here = { lat: c[0], lng: c[1] };
        if (Number.isFinite(Number(nextZoom))) z = Number(nextZoom);
      },
      panBy(offset) { calls.push({ action: "panBy", offset }); },
      _rawPanBy(offset) { calls.push({ action: "panBy", offset }); },
      getSize() { return size; },
      getCenter() { return here; },
      getZoom() { return z; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : (ll.lng ?? ll.lon);
        const p = project(lat, lng);
        const c = project(here.lat, here.lng);
        return { x: size.x / 2 + (p.x - c.x), y: size.y / 2 + (p.y - c.y) };
      },
      containerPointToLatLng(p) {
        const c = project(here.lat, here.lng);
        const scale = 256 * (2 ** z);
        const wx = c.x + (p.x - size.x / 2);
        const wy = c.y + (p.y - size.y / 2);
        const lng = (wx / scale) * 360 - 180;
        const n = Math.PI - ((2 * Math.PI * wy) / scale);
        const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
        return { lat, lng };
      },
    };
    const pxBetween = (a, b) => {
      const p0 = map.latLngToContainerPoint(a);
      const p1 = map.latLngToContainerPoint(b);
      return Math.hypot(p1.x - p0.x, p1.y - p0.y);
    };
    return { map, calls, size, pxBetween };
  }

  it("clampFilmScreenStep refuse un pas de 54 px", () => {
    const { map, pxBetween } = mercatorMap();
    const from = [46.1541, -1.167];
    const to = [46.1541, 1.3];
    assert.ok(pxBetween(from, to) > 50, "le pas synthétique n'atteint pas 54 px");
    const limited = clampFilmScreenStep(map, from, to, FILM_SCREEN_STEP_MAX_PX);
    const step = pxBetween(from, limited);
    assert.ok(step <= FILM_SCREEN_STEP_MAX_PX + 0.6, `pas ${step.toFixed(1)} px non rejeté`);
    assert.ok(step > 20, `clamp trop petit ${step.toFixed(1)}`);
  });

  it("applyFilmCamera : pas synthétique > 30 px rejeté (même chapitre)", () => {
    const { map, calls, pxBetween } = mercatorMap({ lat: 46.1541, lng: -1.167 }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: null, lat: 46.1541, lon: -1.167,
      heading: 140, zoom: 5, now: 0,
    });
    const target = [46.1541, 1.3];
    const before = first.lastCenter;
    assert.ok(pxBetween(before, target) > 50);
    const next = applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: first.lastChapterIdx, lat: target[0], lon: target[1],
      heading: 140, zoom: 5, now: 16,
      lastSetViewAt: first.lastSetViewAt, flyingUntil: first.flyingUntil,
      lastCenter: first.lastCenter, lastBoat: { lat: 46.1541, lon: -1.167 },
      framesSinceReset: first.framesSinceReset, stillAnchor: null,
      boatPx: 54,
    });
    const step = pxBetween(before, next.lastCenter);
    assert.ok(step <= FILM_SCREEN_STEP_MAX_PX + 0.6, `caméra ${step.toFixed(1)} px`);
    assert.notEqual(next.action, "flyTo");
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
  });

  it("stepFilmCamera : pose bateau bornée à 30 px hors flip", () => {
    const { map, pxBetween } = mercatorMap({ lat: 46.1541, lng: -1.167 }, 5);
    const samples = [];
    pushFilmSample(samples, {
      t: 0, lat: 46.1541, lon: -1.167, heading: 140, chapterIdx: 1,
    });
    pushFilmSample(samples, {
      t: 16, lat: 46.1541, lon: 1.3, heading: 140, chapterIdx: 1,
    });
    const next = stepFilmCamera(map, {
      samples,
      now: 16 + FILM_INTERP_DELAY_MS,
      lastChapterIdx: 1,
      zoom: 5,
      baseZoom: 5,
      chapterIdx: 1,
      lastCenter: [46.1541, -1.167],
      lastBoat: { lat: 46.1541, lon: -1.167 },
    });
    const step = pxBetween([46.1541, -1.167], [next.pose.lat, next.pose.lon]);
    assert.ok(step <= FILM_SCREEN_STEP_MAX_PX + 0.6, `bateau ${step.toFixed(1)} px`);
    assert.ok(next.boatPx <= FILM_SCREEN_STEP_MAX_PX + 0.6, `boatPx ${next.boatPx}`);
  });

  it("flip : au plus une action setView, pas un second flyTo", () => {
    const { map, calls } = mercatorMap({ lat: 41.9192, lng: 8.7386 }, 5);
    const first = applyFilmCamera(map, {
      chapterIdx: 4, lastChapterIdx: null, lat: 41.9192, lon: 8.7386,
      heading: 250, zoom: 5, now: 0,
    });
    const views0 = calls.filter((c) => c.action === "setView").length;
    const flip = applyFilmCamera(map, {
      chapterIdx: 5, lastChapterIdx: first.lastChapterIdx,
      lat: 14.6036, lon: -61.0668, heading: 280, zoom: 5, now: 80,
      lastSetViewAt: first.lastSetViewAt, lastCenter: first.lastCenter,
      lastBoat: { lat: 41.9192, lon: 8.7386 },
    });
    assert.equal(flip.action, "setView");
    assert.equal(calls.filter((c) => c.action === "setView").length - views0, 1);
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
    let st = flip;
    for (let i = 0; i < 8; i++) {
      st = applyFilmCamera(map, {
        chapterIdx: 5, lastChapterIdx: st.lastChapterIdx,
        lat: 14.6036, lon: -61.0668, heading: 280, zoom: 5,
        now: 96 + i * 16,
        lastSetViewAt: st.lastSetViewAt, flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter, lastBoat: { lat: 14.6036, lon: -61.0668 },
        framesSinceReset: st.framesSinceReset, stillAnchor: st.stillAnchor,
      });
      assert.equal(st.action, "hold");
    }
    assert.equal(calls.filter((c) => c.action === "setView").length - views0, 1);
  });

  it("filmPanMaxFrac ne dépasse plus 30 px même si boatPx = 54", () => {
    const frac = filmPanMaxFrac(true, { boatPx: 54, sizeX: 1440 });
    assert.ok(frac * 1440 <= FILM_SCREEN_STEP_MAX_PX + 1e-9, `frac ${frac} → ${(frac * 1440).toFixed(1)} px`);
    assert.ok(FILM_INTRA_JUMP_PX > 54, "un hitch 54 px ne doit plus être une ancre");
  });

  it("setView de reset : lastCenter dérivé 200 px → au plus 30 px depuis le centre visuel", () => {
    const { map, calls, pxBetween } = mercatorMap({ lat: 46.1541, lng: -1.167 }, 5);
    applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: null, lat: 46.1541, lon: -1.167,
      heading: 140, zoom: 5, now: 0,
    });
    const visual = [46.1541, -1.167];
    const drifted = [46.1541, 8.8];
    assert.ok(pxBetween(visual, drifted) > 150);
    const reset = applyFilmCamera(map, {
      chapterIdx: 1, lastChapterIdx: 1, lat: 46.1541, lon: -1.167,
      heading: 140, zoom: 5, now: 600,
      lastCenter: drifted, lastBoat: { lat: 46.1541, lon: -1.167 },
      framesSinceReset: 36, stillAnchor: null, boatPx: 0,
    });
    assert.equal(reset.action, "setView");
    const step = pxBetween(visual, reset.lastCenter);
    assert.ok(step <= FILM_SCREEN_STEP_MAX_PX + 0.6, `reset ${step.toFixed(1)} px`);
    assert.equal(calls.filter((c) => c.action === "flyTo").length, 0);
  });
});
