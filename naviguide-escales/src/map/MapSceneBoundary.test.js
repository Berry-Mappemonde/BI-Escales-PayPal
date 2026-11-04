import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { worldCopyCoords, WORLD_COPY_LON_BOUND } from "../utils/geo.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (file) => readFileSync(join(here, file), "utf8");

describe("MapScene boundary", () => {
  it("retire les hooks Leaflet et le playhead de App", () => {
    const app = read("../App.jsx");
    assert.match(app, /<MapScene/);
    assert.doesNotMatch(app, /useRoutePlayback/);
    assert.doesNotMatch(app, /useWakeLayer/);
    assert.doesNotMatch(app, /useSimulatorMap/);
    assert.doesNotMatch(app, /useFilmCamera/);
  });

  it("garde les objets Leaflet dans un contrôleur add/update/remove", () => {
    const controller = read("./MapSceneController.js");
    const playback = read("./ScenePlaybackController.js");
    assert.match(controller, /SceneLayerRegistry/);
    assert.match(controller, /renderDynamic/);
    assert.match(controller, /syncWake/);
    assert.match(controller, /syncMarkers/);
    assert.match(playback, /SCENE_INTERVAL_MS = 125/);
    assert.match(playback, /HUD_INTERVAL_MS = 250/);
    assert.match(playback, /onFrame/);
    assert.match(playback, /onPublish/);
  });

  it("borne la latitude à ±85 et la longitude à ±540 (une copie de chaque côté)", () => {
    const src = read("./MapSceneController.js");
    const start = src.indexOf("static mount");
    const end = src.indexOf("constructor(map");
    assert.ok(start >= 0 && end > start, "bloc mount() introuvable");
    const mount = src.slice(start, end);
    assert.match(mount, /minZoom:\s*MAP_MIN_ZOOM/);
    assert.match(src, /MAP_MIN_ZOOM = 0/);
    assert.match(src, /WORLD_ZOOM = 2/);
    assert.match(mount, /worldCopyJump:\s*false/);
    assert.match(mount, /maxBoundsViscosity:\s*1/);
    assert.match(src, /MAP_LON_BOUND = 540/);
    assert.match(src, /MAP_LAT_BOUND = 85/);
    assert.match(mount, /maxBounds:\s*MAP_MAX_BOUNDS/);
    assert.doesNotMatch(mount, /-Infinity/);
    assert.doesNotMatch(mount, /Infinity/);
  });

  it("Calage initial Suivre = bateau au centre, zoom plancher", () => {
    const src = read("./MapSceneController.js");
    const start = src.indexOf("  syncInitialCamera()");
    const end = src.indexOf("  liftBoundsForDrawing()");
    assert.ok(start >= 0 && end > start, "syncInitialCamera / liftBoundsForDrawing introuvables");
    const chunk = src.slice(start, end);
    assert.doesNotMatch(chunk, /6\.5/);
    assert.match(chunk, /shouldFrameFollowLive/);
    assert.match(chunk, /frameFollowLive/);
    assert.match(chunk, /shouldPlaceInitialCamera/);
    assert.match(chunk, /setCameraPlaced\(true\)/);
    assert.match(src, /applyFollowCadrage/);
  });

  it("En Tracer la caméra ne reprend pas le zoom bateau", () => {
    const src = read("./MapSceneController.js");
    assert.match(src, /if \(cfg\.filmActive \|\| cfg\.drawingMode\) return/);
    assert.match(src, /this\.config\.drawingMode \|\| !this\.map/);
    assert.match(src, /event\?\.type !== "zoomstart"/);
    assert.match(src, /setMaxBounds\?\.\(null\)/);
  });

  it("Entrée Tracer pose drawingMode et lève maxBounds avant showWorld", () => {
    const app = read("../App.jsx");
    const src = read("./MapSceneController.js");
    assert.match(app, /beginDrawingWorld/);
    assert.match(src, /beginDrawingWorld\(\)/);
    assert.match(src, /drawingMode: true/);
    assert.match(src, /keepBoundsLifted/);
    const enter = src.indexOf("if (!previous.drawingMode && this.config.drawingMode)");
    assert.ok(enter >= 0, "branche entrée drawingMode introuvable");
    const enterChunk = src.slice(enter, enter + 220);
    assert.match(enterChunk, /liftBoundsForDrawing\(\)/);
    assert.match(enterChunk, /showWorld\(\{ keepBoundsLifted: true \}\)/);
    const showAt = src.indexOf("showWorld({ keepBoundsLifted = false } = {})");
    const showEnd = src.indexOf("  resetCameraForView()");
    assert.ok(showAt >= 0 && showEnd > showAt, "showWorld introuvable");
    const showChunk = src.slice(showAt, showEnd);
    assert.match(showChunk, /leaveLifted = keepBoundsLifted \|\| this\.config\.drawingMode/);
    assert.match(showChunk, /if \(!leaveLifted && bounds\)/);
    assert.match(app, /showWorld\?\.\(\{ keepBoundsLifted: true \}\)/);
    assert.match(src, /_pendingDrawUntil/);
    assert.match(src, /_worldLockUntil/);
    assert.match(src, /endDrawingWorld\(\)/);
    assert.match(app, /endDrawingWorld/);
  });

  it("désactive le zoom haut-gauche et le pose en bas à droite", () => {
    const src = read("./MapSceneController.js");
    const start = src.indexOf("static mount");
    const end = src.indexOf("constructor(map");
    assert.ok(start >= 0 && end > start, "bloc mount() introuvable");
    const mount = src.slice(start, end);
    assert.match(mount, /zoomControl:\s*false/);
    assert.match(mount, /L\.control\.zoom\(\{\s*position:\s*"bottomright"\s*\}\)/);
    const css = read("../index.css");
    assert.match(css, /\.leaflet-control-zoom/);
    assert.match(css, /flex-direction:\s*row/);
    assert.match(css, /\.leaflet-bottom\.leaflet-right \.leaflet-control/);
  });

  it("après un grand glissement à droite, des points de route existent dans la fenêtre est", () => {
    const line = [];
    for (let lon = -360; lon <= 8; lon += 8) line.push([lon, 12]);
    const east = worldCopyCoords(line).flat().filter(([lon]) => (
      lon >= 360 && lon <= WORLD_COPY_LON_BOUND
    ));
    assert.ok(east.length > 0, "fenêtre est [360, 540] sans point de route");
    const src = read("./MapSceneController.js");
    assert.match(src, /worldCopyOffsets/);
    assert.match(src, /worldCopyLngs\(point\.lon\)/);
  });

  it("trace une jambe air en dash noir non interactif", () => {
    const src = read("./MapSceneController.js");
    assert.match(src, /officialRouteLineStyle/);
    assert.match(src, /interactive,\s*$/m);
    assert.match(src, /pts\[i \+ 1\]\.jump/);
    const styleSrc = read("../utils/berryLegs.js");
    assert.match(styleSrc, /color: "#111111"/);
    assert.match(styleSrc, /dash: "7 7"/);
    assert.match(styleSrc, /interactive: false/);
  });
});
