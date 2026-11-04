import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ESCALE_POPUP_MAX_HEIGHT,
  ESCALE_POPUP_MAX_WIDTH,
  createEscalePopupOptions,
  ensureEscalePopup,
  findParkedBoatMarker,
  findWaypointMarker,
  handleWaypointMarkerClick,
  isEscaleCloseClick,
  requestEscaleClose,
  shouldCloseEscaleSheet,
} from "./escalePopup.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "EscalePopup.jsx"), "utf8");
const sheet = readFileSync(join(here, "EscaleSheet.jsx"), "utf8");
const sceneSrc = readFileSync(join(here, "..", "map", "MapSceneController.js"), "utf8");
const sidebar = readFileSync(join(here, "Sidebar.jsx"), "utf8");
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");

function fakePopup() {
  return {
    ll: null,
    content: null,
    setLatLng(v) {
      this.ll = Array.isArray(v) ? { lat: v[0], lng: v[1] } : v;
      return this;
    },
    getLatLng() { return this.ll; },
    setContent(c) { this.content = c; return this; },
    openOn() { return this; },
    remove() { return this; },
  };
}

function fakeMarker(lat, lng, stop) {
  return {
    ll: { lat, lng },
    _naviguideWaypoint: stop,
    getLatLng() { return this.ll; },
  };
}

describe("EscalePopup — contrat", () => {
  it("contenu = EscaleSheet, croix, pas de ListenButton, ≤ 340 × 260", () => {
    assert.match(src, /data-testid="escale-popup"/);
    assert.match(src, /<EscaleSheet/);
    assert.match(src, /onClose/);
    assert.match(sheet, /data-testid="escale-close"/);
    assert.match(sheet, /×|<X /);
    assert.doesNotMatch(src, /ListenButton/);
    assert.doesNotMatch(sheet, /ListenButton/);
    assert.equal(ESCALE_POPUP_MAX_WIDTH, 340);
    assert.equal(ESCALE_POPUP_MAX_HEIGHT, 260);
    assert.match(src, /ESCALE_POPUP_MAX_WIDTH/);
    assert.match(src, /ESCALE_POPUP_MAX_HEIGHT/);
    assert.match(src, /overflowY:\s*"auto"/);
  });

  it("L.popup ancré au drapeau : pas de croix Leaflet, 340 px, Échap", () => {
    const opts = createEscalePopupOptions();
    assert.equal(opts.autoPan, true);
    assert.equal(opts.closeButton, false);
    assert.equal(opts.className, "escale-popup");
    assert.equal(opts.maxWidth, 340);
    assert.equal(opts.closeOnClick, false);
    const created = [];
    const L = {
      popup(o) {
        const p = { ...fakePopup(), opts: o };
        created.push(p);
        return p;
      },
    };
    const first = ensureEscalePopup(null, L);
    assert.equal(ensureEscalePopup(first, L), first);
    assert.equal(created.length, 1);
    assert.match(src, /attachEscalePopup/);
    assert.match(src, /keydown/);
    assert.match(src, /Escape/);
    assert.match(sceneSrc, /this\.escalePopup = attachEscalePopup\(this, L\)/);
    assert.match(sceneSrc, /this\.escalePopup\?\.sync\(\)/);
  });

  it("trouve le drapeau de l'escale ouverte (copie la plus proche)", () => {
    const ajaccio = { name: "Ajaccio (Corse)", lat: 41.9192, lon: 8.7386 };
    const scene = {
      map: { getCenter: () => ({ lng: 8.7 }) },
      waypointMarkers: new Map([
        ["route:2:0", fakeMarker(41.9192, 8.7386, ajaccio)],
        ["route:2:1", fakeMarker(41.9192, 8.7386 + 360, ajaccio)],
        ["route:0:0", fakeMarker(46.15, -1.15, { name: "La Rochelle", lat: 46.15, lon: -1.15 })],
      ]),
    };
    const found = findWaypointMarker(scene, ajaccio);
    assert.equal(found.getLatLng().lng, 8.7386);
    assert.equal(findWaypointMarker(scene, { name: "Nouméa", lat: -22, lon: 166 }), null);
  });

  it("Fiche du catamaran parqué à Cayenne, pas le drapeau Halifax", () => {
    const cayenne = { name: "Cayenne (Guyane)", lat: 4.93, lon: -52.35 };
    const halifax = { name: "Halifax (Nouvelle-Écosse)", lat: 44.65, lon: -63.57 };
    const boat = fakeMarker(4.93, -52.35, cayenne);
    const scene = {
      map: { getCenter: () => ({ lng: -52.3 }) },
      waypointMarkers: new Map([
        ["route:h:0", fakeMarker(44.65, -63.57, halifax)],
        ["route:c:0", fakeMarker(4.93, -52.35, cayenne)],
      ]),
      markerSets: new Map([["live", [boat]]]),
    };
    assert.equal(findParkedBoatMarker(scene, cayenne), boat);
    assert.equal(findWaypointMarker(scene, cayenne), boat);
    assert.notEqual(findWaypointMarker(scene, cayenne), scene.waypointMarkers.get("route:h:0"));
  });

  it("App relie le clic drapeau et la légende au même état ; plus dans le panneau", () => {
    assert.match(app, /onWaypointClick=\{openEscaleFromUi\}/);
    assert.match(app, /onEscaleSheet=\{openEscaleFromUi\}/);
    assert.match(app, /<EscalePopupHost/);
    assert.doesNotMatch(sidebar, /EscaleSheet/);
    assert.doesNotMatch(app, /escaleStop=\{escaleStop\}/);
    const point = { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7 };
    const calls = { sheet: 0, draw: 0 };
    handleWaypointMarkerClick(false, point, 0, {
      onWaypointClick: () => { calls.sheet += 1; },
      onDrawingWaypointClick: () => { calls.draw += 1; },
    });
    assert.equal(calls.sheet, 1);
    assert.equal(calls.draw, 0);
  });
});

describe("EscalePopup — croix, Échap, pas de fiche en Suivre/Revoir", () => {
  it("la croix appelle onClose", () => {
    let n = 0;
    const event = {
      target: { closest: (sel) => (sel === "[data-testid='escale-close']" ? {} : null) },
      preventDefault() {},
      stopPropagation() {},
    };
    assert.equal(isEscaleCloseClick(event), true);
    assert.equal(isEscaleCloseClick({ target: { closest: () => null } }), false);
    requestEscaleClose({ onClose: () => { n += 1; } });
    assert.equal(n, 1);
    assert.match(src, /requestEscaleClose/);
    assert.match(src, /addEventListener\?\.\("click"/);
    assert.match(src, /keydown/);
    assert.match(sheet, /data-testid="escale-close"/);
    assert.match(sheet, /onMouseDown/);
    assert.match(sheet, /onClose\(\)/);
  });

  it("Suivre / Revoir vident la fiche ; le film ne la rouvre pas", () => {
    assert.equal(shouldCloseEscaleSheet({ nextView: "suivre" }), true);
    assert.equal(shouldCloseEscaleSheet({ replayStarting: true }), true);
    assert.equal(shouldCloseEscaleSheet({ replayActive: true }), true);
    assert.equal(shouldCloseEscaleSheet({ nextView: "tracer" }), true);
    assert.match(app, /shouldCloseEscaleSheet/);
    assert.match(app, /if \(replay\.active\) return/);
    const prev = globalThis.__naviguideIgnoreEscaleOpen;
    globalThis.__naviguideIgnoreEscaleOpen = Date.now() + 1000;
    const calls = { sheet: 0 };
    const ignored = handleWaypointMarkerClick(false, { name: "Ajaccio", lat: 41.9, lon: 8.7 }, 0, {
      onWaypointClick: () => { calls.sheet += 1; },
    });
    assert.equal(ignored, "ignore");
    assert.equal(calls.sheet, 0);
    globalThis.__naviguideIgnoreEscaleOpen = prev;
  });
});
