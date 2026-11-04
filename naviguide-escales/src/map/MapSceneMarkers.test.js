import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { applyFilmCamera } from "./filmCamera.js";
import { handleWaypointMarkerClick } from "../components/escalePopup.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "MapSceneController.js"), "utf8");

describe("MapSceneController — boats", () => {
  it("our `visible` decision is never overridden by the actor's own flag (spread first)", () => {
    for (const role of ["simulation", "ghost", "side", "plane", "drawing"]) {
      const idx = src.indexOf(`this.syncMarker("${role}", {`);
      assert.ok(idx > 0, role);
      const block = src.slice(idx, idx + 260);
      const spread = block.indexOf("...");
      const visible = block.indexOf("visible:");
      assert.ok(spread > 0 && visible > spread, `${role}: spread must come before visible`);
    }
  });

  it("entering or leaving the drawing mode re-syncs the boats even while paused; flags stay put while the camera follows", () => {
    assert.match(src, /previous\.drawingMode !== this\.config\.drawingMode[\s\S]{0,120}this\.syncMarkers\(this\.currentCast, this\.currentPlayback\)/);
    assert.match(src, /if \(reason === "follow"\) return;/);
    assert.match(src, /isCameraFollowing\(\)/);
  });
});

describe("MapSceneController — caméra film", () => {
  it("aucun flyTo hors changement de chapitre (faux map)", () => {
    const calls = { flyTo: 0, setView: 0 };
    const map = {
      flyTo() { calls.flyTo += 1; },
      setView() { calls.setView += 1; },
      panBy() {},
      _rawPanBy() {},
      getZoom() { return 5; },
      getSize() { return { x: 1000, y: 800 }; },
      getCenter() { return { lat: 46, lng: -1 }; },
      latLngToContainerPoint(ll) {
        const lat = Array.isArray(ll) ? ll[0] : ll.lat;
        const lng = Array.isArray(ll) ? ll[1] : ll.lng;
        return { x: (lng + 1) * 10, y: (50 - lat) * 10 };
      },
      containerPointToLatLng(p) { return { lat: 50 - p.y / 10, lng: p.x / 10 - 1 }; },
      getBounds() {
        return { getNorth: () => 10, getSouth: () => 0, getEast: () => 10, getWest: () => 0 };
      },
    };
    let st = { lastChapterIdx: null, lastSetViewAt: 0, flyingUntil: 0, lastCenter: null };
    const step = (chapterIdx, now, lat = 46, lon = -1) => {
      const next = applyFilmCamera(map, {
        chapterIdx,
        lastChapterIdx: st.lastChapterIdx,
        lat,
        lon,
        heading: 240,
        zoom: 5,
        now,
        lastSetViewAt: st.lastSetViewAt,
        flyingUntil: st.flyingUntil,
        lastCenter: st.lastCenter,
      });
      st = {
        lastChapterIdx: next.lastChapterIdx,
        lastSetViewAt: next.lastSetViewAt,
        flyingUntil: next.flyingUntil,
        lastCenter: next.lastCenter,
      };
      return next;
    };
    assert.equal(step(0, 1000).action, "setView");
    assert.equal(calls.flyTo, 0, "premier mouvement = setView, pas de flyTo");
    assert.equal(calls.setView, 1);
    const mid = step(0, 1030);
    assert.ok(mid.action === "panBy" || mid.action === "hold" || mid.action === "setView", "plus de setView obligatoire par frame");
    assert.equal(calls.flyTo, 0);
    assert.equal(step(1, 5000).action, "setView");
    assert.equal(calls.flyTo, 0, "changement d'étape : un setView, plus de flyTo");
    const after = step(1, 5100);
    assert.notEqual(after.action, "fly-wait");
    assert.equal(calls.flyTo, 0);
    assert.match(src, /if \(cfg\.filmActive\)/);
    assert.match(src, /syncFilmCamera/);
    assert.doesNotMatch(src, /filmActive[\s\S]{0,200}zoomForRemaining/);
  });
});

describe("MapSceneController — zoom", () => {
  it("n'orchestre pas un recalcul d'offsets pendant zoomanim ; zoomend recalcule tout de suite", () => {
    assert.match(src, /map\.on\("zoomanim"/);
    assert.match(src, /map\.on\("zoomend"/);
    assert.match(src, /reason: "zoom"/);
    const animStart = src.indexOf("this.onZoomAnim = ");
    const animEnd = src.indexOf("this.onZoomEnd = ");
    assert.ok(animStart > 0 && animEnd > animStart);
    const anim = src.slice(animStart, animEnd);
    assert.doesNotMatch(anim, /syncWaypoints\(/);
    assert.doesNotMatch(anim, /scheduleWaypoints\(/);
    const zoomEnd = src.slice(src.indexOf("this.onZoomEnd = "), src.indexOf("this.onMoveEnd = "));
    assert.match(zoomEnd, /scheduleWaypoints\(\{ reason: "zoom" \}\)/);
    const schedAt = src.indexOf("  scheduleWaypoints({");
    const schedEnd = src.indexOf("  syncInitialCamera()", schedAt);
    const sched = src.slice(schedAt, schedEnd);
    assert.match(sched, /reason === "zoom"/);
    assert.match(sched, /this\.syncWaypoints\(\)/);
    assert.doesNotMatch(sched, /markerOffsetDelay\([\s\S]{0,40}zoom/);
    assert.match(src, /preferCanvas:\s*true/);
    assert.match(src, /divIconCache/);
    assert.match(src, /stabilizeWorldLng/);
    assert.match(src, /worldCopyKey/);
    assert.match(src, /offsetToIconAnchor/);
    assert.match(src, /zoomControl:\s*false/);
    assert.match(src, /position:\s*"bottomright"/);
  });

  it("clic drapeau hors dessin → onWaypointClick ; en dessin → inchangé", () => {
    const point = { name: "Ajaccio (Corse)", lat: 41.9192, lon: 8.7386 };
    const calls = { sheet: [], draw: [] };
    const callbacks = {
      onWaypointClick: (p, i) => calls.sheet.push([p, i]),
      onDrawingWaypointClick: (p, i) => calls.draw.push([p, i]),
    };
    assert.equal(handleWaypointMarkerClick(false, point, 2, callbacks), "sheet");
    assert.deepEqual(calls.sheet, [[point, 2]]);
    assert.equal(calls.draw.length, 0);
    assert.equal(handleWaypointMarkerClick(true, point, 1, callbacks), "draw");
    assert.deepEqual(calls.draw, [[point, 1]]);
    assert.equal(calls.sheet.length, 1, "le clic dessin n'ouvre pas la fiche");
    assert.match(src, /onWaypointClick\?\.\(marker\._naviguideWaypoint, marker\._naviguideIndex\)/);
    assert.match(src, /if \(marker\._naviguideDrawing\) \{\s*this\.callbacks\.onDrawingWaypointClick/);
    assert.match(src, /const drawingHasPoints = Boolean\(cfg\.drawingMode && \(cfg\.drawnPoints \|\| \[\]\)\.length\)/);
    assert.match(src, /marker\._naviguideDrawing = drawingHasPoints/);
  });

  it("Rond de tracé via drawingPinMetrics, plus d'icône 24×24 décalée", () => {
    assert.match(src, /drawingPinHtml\(index, stamp\)/);
    assert.match(src, /drawingPinMetrics\(\)/);
    assert.doesNotMatch(src, /width:10px;height:10px/);
    assert.doesNotMatch(src, /iconSize: \[24, 24\], iconAnchor: \[12, 12\]/);
  });

  it("Plancher de dézoom identique hors Suivre (plus de MAP_MIN_ZOOM réservé)", () => {
    const start = src.indexOf("  applyZoomFloor()");
    const end = src.indexOf("  liftBoundsForDrawing()");
    assert.ok(start >= 0 && end > start);
    const block = src.slice(start, end);
    assert.match(block, /followMinZoom\(this\.map\.getSize/);
    assert.doesNotMatch(block, /isSuivre/);
    assert.doesNotMatch(block, /worldLock/);
    assert.match(src, /worldViewZoom/);
    assert.match(src, /sceneWorldZoom/);
  });

  it("onMoveEnd ne relance ni /ici ni le récit", () => {
    const start = src.indexOf("this.onMoveEnd = ");
    const end = src.indexOf("this.onUserNavigation = ");
    const block = src.slice(start, end);
    assert.doesNotMatch(block, /\/ici|narrateIci|enqueueStory|fetch\(/);
  });

  it("Cadrage Suivre au plancher, pas zoomForRemaining", () => {
    const camAt = src.indexOf("  syncCamera(cast, snapshot)");
    const camEnd = src.indexOf("  renderDynamic(snapshot)", camAt);
    assert.ok(camAt >= 0 && camEnd > camAt);
    const cam = src.slice(camAt, camEnd);
    assert.match(cam, /liveMode\s*\n\s*\? cadrageZoom/);
    assert.match(cam, /if \(cfg\.isSuivre\)/);
    assert.match(cam, /this\.frameFollowLive\(subject\)/);
    assert.match(cam, /_pendingFollowCadrage/);
    assert.match(src, /if \(cfg\.filmActive \|\| cfg\.drawingMode\) return/);
    assert.match(src, /showWorld\(/);
    assert.match(src, /setView\(WORLD_CENTER, worldZ/);
  });
});
