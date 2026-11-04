import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  isSceneReady,
  pickOfficialLiveClock,
  playheadAligned,
  sceneMaskKey,
  shouldFocusTracerJump,
  shouldKeepSceneVisible,
  shouldPlaceInitialCamera,
  shouldResnapCamera,
} from "./sceneGate.js";

describe("playheadAligned", () => {
  it("Simulation : toujours prêt", () => {
    assert.equal(playheadAligned({ isSuivre: false, playbackNm: 0 }), true);
  });

  it("Suivre : faux tant que le playhead n’est pas sur le live", () => {
    assert.equal(playheadAligned({
      isSuivre: true,
      previewing: false,
      playbackNm: 0,
      liveFilmNm: 18400,
    }), false);
    assert.equal(playheadAligned({
      isSuivre: true,
      previewing: false,
      playbackNm: 18401,
      liveFilmNm: 18400,
    }), true);
  });
});

describe("isSceneReady", () => {
  it("attend route + caméra + live aligné en Suivre", () => {
    assert.equal(isSceneReady({
      routeReady: true,
      hasRoute: true,
      cameraPlaced: false,
      playheadReady: true,
      isSuivre: true,
      hasLive: true,
    }), false);
    assert.equal(isSceneReady({
      routeReady: true,
      hasRoute: true,
      cameraPlaced: true,
      playheadReady: false,
      isSuivre: true,
      hasLive: true,
    }), false);
    assert.equal(isSceneReady({
      routeReady: true,
      hasRoute: true,
      cameraPlaced: true,
      playheadReady: true,
      isSuivre: true,
      hasLive: true,
    }), true);
  });

  it("App aligne le playhead sans jump et masque jusqu’à sceneReady", () => {
    const app = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../App.jsx"),
      "utf8",
    );
    const scene = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../map/MapSceneController.js"),
      "utf8",
    );
    assert.match(app, /playback\.seek\(target, \{ jump: Boolean\(live\.replay\) \}\)/, "live: eased seek; replay: jump every frame");
    assert.match(app, /scene-load-mask/);
    assert.match(app, /isSceneReady/);
    assert.match(scene, /shouldPlaceInitialCamera/);
    assert.match(scene, /this\.userNavigated = true/);
    assert.match(scene, /shouldResnapCamera/);
    assert.match(app, /clock: voyage\.clock/);
    assert.match(app, /shouldKeepSceneVisible/);
    assert.match(app, /sceneMaskKey/);
  });
});

describe("pickOfficialLiveClock", () => {
  const server = { id: "server" };
  const clientA = { id: "client-a" };
  const clientB = { id: "client-b" };

  it("prend le serveur dès qu’il existe, sans suivre une polaire tardive", () => {
    assert.deepEqual(pickOfficialLiveClock(null, clientA, null), {
      liveClock: clientA,
      frozenClient: clientA,
    });
    assert.deepEqual(pickOfficialLiveClock(null, clientB, clientA), {
      liveClock: clientA,
      frozenClient: clientA,
    });
    assert.deepEqual(pickOfficialLiveClock(server, clientB, clientA), {
      liveClock: server,
      frozenClient: clientA,
    });
  });
});

describe("shouldKeepSceneVisible", () => {
  it("garde la scène ouverte si la route est toujours là", () => {
    assert.equal(shouldKeepSceneVisible({
      revealed: true,
      routeReady: true,
      hasRoute: true,
    }), true);
    assert.equal(shouldKeepSceneVisible({
      revealed: true,
      routeReady: false,
      hasRoute: true,
    }), false);
  });
});

describe("sceneMaskKey", () => {
  it("ne dit plus « calcul des routes » une fois la route prête", () => {
    assert.equal(sceneMaskKey({ routeReady: false }), "calculatingRoutes");
    assert.equal(sceneMaskKey({ routeReady: true }), "positioningExpedition");
  });
});

describe("shouldPlaceInitialCamera", () => {
  it("laisse l’utilisateur garder sa vue s’il a déjà navigué", () => {
    assert.equal(shouldPlaceInitialCamera({ userNavigated: false }), true);
    assert.equal(shouldPlaceInitialCamera({ userNavigated: true }), false);
  });
});

describe("shouldFocusTracerJump", () => {
  it("recentre seulement un saut arrêté en Tracer", () => {
    assert.equal(shouldFocusTracerJump({ isTracer: true, playing: false }), true);
    assert.equal(shouldFocusTracerJump({ isTracer: true, playing: true }), false);
    assert.equal(shouldFocusTracerJump({ isTracer: false, playing: false }), false);
  });
});

describe("shouldResnapCamera", () => {
  it("recadre si le live saute l’antiméridien (70° → −191°)", () => {
    assert.equal(shouldResnapCamera(null, { lat: -22.7, lon: -191.16 }), true);
    assert.equal(shouldResnapCamera({ lat: -19.8, lon: 70.5 }, { lat: -22.7, lon: -191.16 }), true);
    assert.equal(shouldResnapCamera({ lat: -22.76, lon: -191.15 }, { lat: -22.76, lon: -191.16 }), false);
  });
});
