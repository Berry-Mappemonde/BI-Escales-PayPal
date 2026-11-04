import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  applyFollowCadrage,
  followCadrageCenter,
  followCadrageZoom,
  shouldFrameFollowLive,
} from "./followCadrage.js";

const here = dirname(fileURLToPath(import.meta.url));
const controller = readFileSync(join(here, "MapSceneController.js"), "utf8");

const LIVE = { lat: -16.5, lon: -151.7 };
const SIZE = { x: 1280, y: 800 };

function fakeMap(views) {
  return {
    getSize: () => SIZE,
    options: { zoomSnap: 0.25 },
    setView(center, zoom) { views.push({ center: [...center], zoom }); },
  };
}

function tickCadrage({ live, userNavigated = false, isSuivre = true, filmActive = false, drawingMode = false } = {}) {
  const views = [];
  const map = fakeMap(views);
  let initialLive = null;
  const tick = () => {
    if (shouldFrameFollowLive({
      isSuivre, filmActive, drawingMode, live, userNavigated, initialLive,
    })) {
      applyFollowCadrage(map, live, { minZoom: 0 });
      initialLive = { lat: live.lat, lon: live.lon };
    }
  };
  return { views, tick, getInitial: () => initialLive, setInitial: (v) => { initialLive = v; } };
}

describe("Cadrage Suivre (bateau + plancher)", () => {
  it("première position live → setView(bateau, plancher) une fois", () => {
    const { views, tick } = tickCadrage({ live: LIVE });
    tick();
    assert.equal(views.length, 1);
    assert.deepEqual(views[0].center, followCadrageCenter(LIVE));
    assert.equal(views[0].zoom, followCadrageZoom(SIZE, 0.25, 0));
    assert.equal(views[0].zoom, 2.5);
    tick();
    assert.equal(views.length, 1, "pas de second setView pour la même position");
  });

  it("entrée Suivre (initialLive remis à zéro) → même cadrage", () => {
    const { views, tick, setInitial } = tickCadrage({ live: LIVE });
    tick();
    assert.equal(views.length, 1);
    setInitial(null);
    tick();
    assert.equal(views.length, 2);
    assert.equal(views[1].zoom, 2.5);
    assert.equal(views[1].center[0], LIVE.lat);
  });

  it("utilisateur a navigué → pas de recadrage", () => {
    const { views, tick } = tickCadrage({ live: LIVE, userNavigated: true });
    tick();
    assert.equal(views.length, 0);
  });

  it("entrée Suivre en attente du live : recadre même si un geste a bougé la carte", () => {
    assert.equal(shouldFrameFollowLive({
      isSuivre: true, live: LIVE, userNavigated: true, pending: true,
    }), true);
    assert.equal(shouldFrameFollowLive({
      isSuivre: true, live: LIVE, userNavigated: true, pending: false,
    }), false);
    assert.equal(shouldFrameFollowLive({
      isSuivre: true, live: LIVE, initialLive: LIVE, pending: true,
    }), true, "clic Suivre recadre même si initialLive avait été mémorisé sans cadrage");
  });

  it("sans live : pas de setView (vue monde provisoire)", () => {
    const { views, tick } = tickCadrage({ live: null });
    tick();
    assert.equal(views.length, 0);
    assert.equal(shouldFrameFollowLive({ isSuivre: true, live: { lat: 1 } }), false);
  });

  it("Tracer, dessin et film ne prennent pas ce cadrage", () => {
    assert.equal(shouldFrameFollowLive({ isSuivre: false, live: LIVE }), false);
    assert.equal(shouldFrameFollowLive({ isSuivre: true, drawingMode: true, live: LIVE }), false);
    assert.equal(shouldFrameFollowLive({ isSuivre: true, filmActive: true, live: LIVE }), false);
  });

  it("le contrôleur applique la règle au calage initial et à l'entrée Suivre", () => {
    const start = controller.indexOf("  syncInitialCamera()");
    const end = controller.indexOf("  sceneWorldZoom()");
    assert.ok(start >= 0 && end > start);
    const chunk = controller.slice(start, end);
    assert.match(chunk, /shouldFrameFollowLive/);
    assert.match(chunk, /frameFollowLive/);
    assert.match(controller, /liveMode\s*\n\s*\? cadrageZoom/);
    assert.match(controller, /resetCameraForView\(\)/);
    assert.match(controller, /this\.initialLive = null/);
    assert.match(controller, /cinemaRecapture !== previous\.cinemaRecapture/);
    assert.doesNotMatch(chunk, /premier calage reste la vue monde/);
  });
});
