import L from "leaflet";
import { catamaranSvg } from "../engine/catamaranIcon.js";
import { interpolateCast, isAirPhase } from "../engine/filmCast.js";
import { wakeCursorAt } from "../engine/filmWake.js";
import {
  haversineNm,
  markerCopyLngs,
  stabilizeWorldLng,
  unwrapLon,
  worldCopyKey,
  worldCopyLineCoords,
  worldCopyLngs,
  worldCopyOffsets,
} from "../utils/geo.js";
import { followMinZoom, worldViewZoom } from "./zoomFloor.js";
import {
  applyFollowCadrage,
  followCadrageZoom as cadrageZoom,
  shouldFrameFollowLive,
} from "./followCadrage.js";
import { computeMarkerOffsets, offsetToIconAnchor, projectRouteSegments } from "../utils/markerOffsets.js";
import {
  cameraLngForBoat,
  drawingPinHtml,
  drawingPinMetrics,
  flagIconMetrics,
  flagMarkerHtml,
  waypointFlagSrcs,
  wrapLon,
} from "../utils/waypointFlags.js";
import {
  shouldPlaceInitialCamera,
  shouldResnapCamera,
} from "../utils/sceneGate.js";
import { applyMarkerRotation } from "../utils/markerRotation.js";
import {
  markerOffsetDelay,
} from "../hooks/useMarkerOffsets.js";
import { createPanes } from "../layers/layerOrder.js";
import { installCompactAttribution } from "../layers/compactAttribution.js";
import {
  ROUTE_CASING_COLOR,
  ROUTE_CASING_WEIGHT,
  ROUTE_MAIN_WEIGHT,
  tileAttribution,
  TILE_URLS,
  WAKE_DONE_COLOR,
  WAKE_REST_COLOR,
} from "../layers/styles.js";
import { SceneLayerRegistry } from "./SceneLayerRegistry.js";
import { routeDrawPlan } from "./routeDrawPlan.js";
import { ScenePlaybackController } from "./ScenePlaybackController.js";
import {
  filmChapterZoom,
  filmTilesReady,
  preloadFilmTiles,
  pushFilmSample,
  stepFilmCamera,
  tilesAlongLeg,
} from "./filmCamera.js";
import { attachEventBubble } from "../components/EventBubble.jsx";
import { attachEscalePopup } from "../components/EscalePopup.jsx";
import { officialAirRouteStyles, officialRouteLineStyle } from "../utils/berryLegs.js";

const TELEPORT_NM = 80;
const EXIT_HOLD_MS = 1500;   // zoom de sortie du film tenu 1,5 s au plus, puis relâché (KO #350)
/** Une copie du monde de chaque côté : ±180° + ±360°. */
export const MAP_LON_BOUND = 540;
export const MAP_LAT_BOUND = 85;
export const MAP_MAX_BOUNDS = [[-MAP_LAT_BOUND, -MAP_LON_BOUND], [MAP_LAT_BOUND, MAP_LON_BOUND]];
/** Vue monde (accueil provisoire sans live, entrée Tracer) : centre historique, zoom 2. */
export const WORLD_CENTER = [22, 5];
export const WORLD_ZOOM = 2;
/**
 * Zoom 2 + maxBounds viscosité 1 : sur un écran plus haut que le globe
 * (1024 px à z=2), Leaflet refuse le dézoom (plan s4 D4', KO #327).
 * minZoom 0 laisse toujours atteindre la vue monde.
 */
export const MAP_MIN_ZOOM = 0;

function baseTileOptions(lang = "fr") {
  return {
    attribution: tileAttribution(lang),
    updateWhenZooming: true,
    updateWhenIdle: false,
    keepBuffer: 8,
    // Hors ±540° le maxBounds coupe : une copie de tuiles de chaque côté, pas l'infini.
    noWrap: false,
  };
}

/** Une tuile en erreur ne laisse pas un carré blanc : on la cache, le fond de carte reste. */
function bindQuietTiles(layer) {
  layer.on("tileerror", (ev) => {
    const tile = ev?.tile;
    if (tile) tile.style.visibility = "hidden";
  });
  return layer;
}

const WAKE_STYLE = {
  color: WAKE_DONE_COLOR,
  weight: 4,
  opacity: 0.92,
  pane: "route",
  interactive: false,
};

const REST_STYLE = {
  color: WAKE_REST_COLOR,
  weight: 4,
  opacity: 0.88,
  pane: "route",
  interactive: false,
};

function latLngs(coords, worldOffset = 0) {
  return coords.map(([lon, lat]) => [lat, lon + worldOffset]);
}

function addRouteLine(group, coords, { color, weight, dash, pane = "route", interactive = true }) {
  if (!coords || coords.length < 2) return;
  worldCopyLineCoords(coords).forEach((copy) => {
    L.polyline(copy.map(([lon, lat]) => [lat, lon]), {
      color,
      weight,
      dashArray: dash,
      pane,
      interactive,
    }).addTo(group);
  });
}

function addWorldLine(group, coords, style) {
  if (!coords || coords.length < 2) return;
  worldCopyLineCoords(coords).forEach((copy) => {
    L.polyline(copy.map(([lon, lat]) => [lat, lon]), style).addTo(group);
  });
}

function isSidePointIndex(episodes, index) {
  return (episodes || []).some((ep) => index > ep.ja && index < ep.jb);
}

function staticWakeParts(flat) {
  const points = flat?.points || [];
  const episodes = flat?.episodes || [];
  const parts = [];
  const partByPoint = new Array(points.length);
  const linePointByIndex = new Array(points.length);
  let current = null;
  points.forEach((point, index) => {
    if (!Number.isFinite(point?.lon) || !Number.isFinite(point?.lat)) return;
    if (point.air && !point.jump) {
      current = null;
      return;
    }
    if (isSidePointIndex(episodes, index)) {
      current = null;
      return;
    }
    if (!current || point.jump) {
      current = [];
      parts.push(current);
    }
    const lon = current.length ? unwrapLon(current.at(-1)[0], point.lon) : point.lon;
    const linePoint = [lon, point.lat];
    current.push(linePoint);
    partByPoint[index] = parts.length - 1;
    linePointByIndex[index] = linePoint;
  });
  return { points, parts, partByPoint, linePointByIndex };
}

function createWorldLines(group, style, offsets) {
  return offsets.map(() => L.polyline([], style).addTo(group));
}

function clearDoneLines(lines) {
  lines.forEach((worldLines) => worldLines.forEach((line) => line.setLatLngs([])));
}

function appendDonePoint(geometry, index) {
  const point = geometry.linePointByIndex[index];
  const partIndex = geometry.partByPoint[index];
  if (!point || partIndex == null) return;
  const offsets = geometry.worldOffsets || [0];
  geometry.doneLines[partIndex].forEach((line, worldIndex) => {
    line.addLatLng([point[1], point[0] + offsets[worldIndex]]);
  });
}

function setWakeTail(lines, from, to, offsets = [0]) {
  if (!from || !to) {
    lines.forEach((line) => line.setLatLngs([]));
    return;
  }
  const coords = [[from.lon, from.lat], [to.lon, to.lat]];
  lines.forEach((line, index) => line.setLatLngs(latLngs(coords, offsets[index] || 0)));
}

function zoomForRemaining(nm) {
  if (nm > 1800) return 3;
  if (nm > 500) return 4;
  if (nm > 120) return 5;
  if (nm > 30) return 6;
  return 7;
}

function planeHtml() {
  return `<div class="plane-icon marker-rotatable" data-marker-rotatable style="width:64px;height:64px;">
    <svg viewBox="0 0 24 24" width="64" height="64" aria-label="avion">
      <path fill="#f8fafc" stroke="#22d3ee" stroke-width="0.8"
        d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5L21 16z"/>
    </svg>
  </div>`;
}

function markerIcon(className, html) {
  return L.divIcon({
    className,
    html,
    iconSize: [64, 64],
    iconAnchor: [32, 32],
  });
}

/**
 * Single owner for the map's mutable Leaflet objects.
 *
 * Static changes call `update()`; animation frames only call `renderDynamic()`.
 * Every object is registered once and follows an explicit add/update/remove
 * lifecycle until `dispose()` tears the scene down.
 */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export class MapSceneController {
  static mount(container, callbacks) {
    const map = L.map(container, {
      center: WORLD_CENTER,
      zoom: WORLD_ZOOM,
      zoomSnap: 0.25,
      fadeAnimation: false,
      minZoom: MAP_MIN_ZOOM,
      maxZoom: 18,
      worldCopyJump: false,
      preferCanvas: true,
      maxBounds: MAP_MAX_BOUNDS,
      maxBoundsViscosity: 1,
      zoomControl: false,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    createPanes(map);
    return new MapSceneController(map, callbacks);
  }

  constructor(map, callbacks = {}) {
    this.map = map;
    this.callbacks = callbacks;
    this.layers = new SceneLayerRegistry();
    this.config = {};
    this.baseLayer = bindQuietTiles(L.tileLayer(TILE_URLS.dark, baseTileOptions("fr"))).addTo(map);
    this.baseLayer._naviguideUrl = TILE_URLS.dark;
    this.baseLayer._naviguideAttr = tileAttribution("fr");
    this.releaseCompactAttribution = installCompactAttribution(map);
    this.wakeGeometry = null;
    this.markerSets = new Map();
    this.waypointMarkers = new Map();
    this.waypointLastOffsets = [];
    this.waypointPrimaryLngs = new Map();
    this.waypointSourceStamp = "";
    this.markerPrimaryLngs = new Map();
    this.divIconCache = new Map();
    this.currentPlayback = null;
    this.currentCast = null;
    this.routeInputs = null;
    this.altDraft = Symbol("uninitialized");
    this.waypointInputs = null;
    this.waypointsDirty = true;
    this.waypointTimer = null;
    this.cameraPlaced = false;
    this.userNavigated = false;
    this._pendingFollowCadrage = false;
    this.ignoreUserNavigation = false;
    this.ignoreUserNavigationTimer = 0;
    this.camera = {
      lastFollow: 0,
      lastJump: 0,
      lastPos: null,
      followLon: null,
      lastPhase: null,
      resetKey: null,
      recapture: null,
      focus: null,
      filmChapterIdx: null,
      filmZoom: null,
      filmZoomBase: null,
      filmSetViewAt: 0,
      filmFlyingUntil: 0,
      filmLastCenter: null,
      filmFramesSinceReset: 0,
      filmLastBoat: null,
      filmStillAnchor: null,
      filmZoomHold: null,
      exitHold: false,
      exitHoldUntil: null,
      exitHoldZoom: null,
    };
    this._mapStop = map.stop.bind(map);
    map.stop = (...args) => {
      if (this.config?.filmActive) {
        const z = map.getZoom?.();
        if (Number.isFinite(z)) this.camera.filmZoomHold = z;
      }
      return this._mapStop(...args);
    };
    this.filmLoopRaf = 0;
    this.filmSamples = [];
    this.filmPose = null;
    this.filmPreload = { key: "", images: [] };
    this.playback = new ScenePlaybackController({
      onFrame: (snapshot) => this.renderDynamic(snapshot),
      onPublish: (snapshot) => this.publishPlayback(snapshot),
    });
    this.zoomAnimating = false;
    this.zoomJustEnded = false;
    this.waypointZoom = map.getZoom();
    this.onZoomAnim = () => {
      this.zoomAnimating = true;
    };
    this.onZoomEnd = () => {
      this.zoomAnimating = false;
      this.zoomJustEnded = true;
      this.applyZoomFloor();
      this.scheduleWaypoints({ reason: "zoom" });
      this.waypointZoom = this.map.getZoom();
      if (this.ignoreUserNavigation) {
        this.restoreExitZoom();
      } else {
        // Zoom de l'utilisateur : le zoom de sortie du film ne doit plus rien imposer (KO #350, 27 sept. :
        // après Revoir, chaque zoom était aussitôt annulé — impossible de dézoomer).
        this.releaseExitZoom();
      }
    };
    this.onMoveEnd = () => {
      // Pas de sac ni de récit ici — seulement copies bateau + offsets.
      if (this.zoomAnimating) return;
      if (this.zoomJustEnded) {
        this.zoomJustEnded = false;
        this.waypointZoom = this.map.getZoom();
        return;
      }
      this.syncDynamicWorldCopies();
      // A pan the camera made while following the boat: the flags
      // keep their offsets — recomputing them at every step made them jump.
      // A zoom (projection change) or a pan the camera did not make: recompute.
      this.scheduleWaypoints({ reason: this.isCameraFollowing() && this.map.getZoom() === this.waypointZoom ? "follow" : "move" });
      this.waypointZoom = this.map.getZoom();
    };
    this.onUserNavigation = (event) => {
      if (this.ignoreUserNavigation) return;
      this.userNavigated = true;
      // zoomstart + stop() annule la molette (KO #327). On n'arrête un flyTo
      // que sur un glisser.
      if (event?.type !== "zoomstart") this.map.stop();
      this.callbacks.onManualNavigation?.();
    };
    map.on("zoomanim", this.onZoomAnim);
    map.on("zoomend", this.onZoomEnd);
    map.on("moveend", this.onMoveEnd);
    map.on("zoomstart", this.onUserNavigation);
    map.on("dragstart", this.onUserNavigation);
    this.onResize = () => this.applyZoomFloor();
    map.on("resize", this.onResize);
    this.applyZoomFloor();
    this.eventBubble = attachEventBubble(this, L);
    this.escalePopup = attachEscalePopup(this, L);
    if (this.escalePopup) {
      this.escalePopup.setSheet?.(null);
      this.escalePopup.setSheet = () => {};
      this.escalePopup.sync = () => {};
      this.escalePopup.hide?.();
    }
  }

  /** Marqueur du bateau « à l'écran » (copie monde 0) — ancre de la bulle F4. */
  mainBoatMarker() {
    const liveMode = this.config.isSuivre && this.config.live && !this.config.previewing;
    const order = this.config.filmActive || liveMode
      ? ["live", "ghost", "simulation", "drawing"]
      : ["simulation", "live", "ghost", "drawing"];
    for (const role of order) {
      const marker = (this.markerSets.get(role) || [])[0];
      if (marker) return marker;
    }
    return null;
  }

  get api() {
    return {
      getMap: () => this.map,
      getView: () => ({ center: this.map.getCenter(), zoom: this.map.getZoom() }),
      setView: (center, zoom, options) => this.programmaticMove(() => this.map.setView(center, zoom, options)),
      showWorld: (opts) => this.showWorld(opts),
      beginDrawingWorld: () => this.beginDrawingWorld(),
      endDrawingWorld: () => this.endDrawingWorld(),
      playback: {
        play: () => this.playback.play(),
        pause: () => this.playback.pause(),
        toggle: () => this.playback.toggle(),
        seek: (nm, options) => this.playback.seek(nm, options),
        setProfile: (profile) => this.playback.setProfile(profile),
      },
      briefing: {
        focus: (place, boat) => this.focusBriefingPlace(place, boat),
        clear: () => this.clearBriefingFocus(),
      },
    };
  }

  /**
   * Briefing link "voir sur la carte": pin the named place, draw a dashed line
   * from the boat, and fit both in view. Counts as a manual navigation so the
   * camera does not snap back to the boat until the skipper recaptures it.
   */
  focusBriefingPlace(place, boat) {
    const lat = Number(place?.lat);
    const lon = Number(place?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    this.clearBriefingFocus();
    const group = L.layerGroup();
    const label = String(place.name || "").slice(0, 60);
    const icon = L.divIcon({
      className: "briefing-focus-pin",
      html: `<div class="briefing-focus-dot"></div><div class="briefing-focus-label">${escapeHtml(label)}</div>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    });
    L.marker([lat, lon], { icon, pane: "briefing-focus", interactive: false, keyboard: false }).addTo(group);
    const bounds = L.latLngBounds([[lat, lon]]);
    const bLat = Number(boat?.lat);
    const bLon = Number(boat?.lon);
    if (Number.isFinite(bLat) && Number.isFinite(bLon)) {
      L.polyline([[bLat, bLon], [lat, lon]], {
        pane: "briefing-focus",
        color: "#7dd3fc",
        weight: 1.5,
        dashArray: "4 6",
        opacity: 0.9,
        interactive: false,
      }).addTo(group);
      bounds.extend([bLat, bLon]);
    }
    group.addTo(this.map);
    this.briefingFocus = group;
    this.userNavigated = true;
    this.callbacks.onManualNavigation?.();
    this.programmaticMove(() => this.map.fitBounds(bounds.pad(0.35), {
      paddingTopLeft: [340, 60],
      paddingBottomRight: [340, 120],
      maxZoom: 13,
      animate: true,
    }));
    return true;
  }

  clearBriefingFocus() {
    if (this.briefingFocus) {
      this.briefingFocus.remove();
      this.briefingFocus = null;
    }
  }

  setCallbacks(callbacks) {
    this.callbacks = callbacks;
  }

  update(next) {
    const incoming = next || {};
    if (this._pendingDrawUntil) {
      if (incoming.drawingMode) {
        this._pendingDrawUntil = 0;
      } else if (Date.now() < this._pendingDrawUntil) {
        next = { ...incoming, drawingMode: true };
      } else {
        this._pendingDrawUntil = 0;
      }
    }
    const previous = this.config;
    const previousView = previous.view;
    this.config = { ...this.config, ...next };
    if (
      this.config.isSuivre
      && Number.isFinite(Number(previous.cinemaRecapture))
      && this.config.cinemaRecapture !== previous.cinemaRecapture
    ) {
      this._pendingFollowCadrage = true;
    }
    if (!previous.filmActive && this.config.filmActive) {
      this.camera.filmChapterIdx = null;
      this.camera.filmZoom = null;
      this.camera.filmZoomBase = null;
      this.camera.filmSetViewAt = 0;
      this.camera.filmFlyingUntil = 0;
      this.camera.filmLastCenter = null;
      this.camera.filmFramesSinceReset = 0;
      this.camera.filmLastBoat = null;
      this.camera.filmStillAnchor = null;
      this.camera.filmZoomHold = null;
      this.filmSamples = [];
      this.filmPose = null;
      this.filmPreload = { key: "", images: [] };
      this.ensureFilmCameraLoop();
    }
    if (previous.filmActive && !this.config.filmActive) {
      this.stopFilmCameraLoop();
      this.filmSamples = [];
      this.filmPose = null;
      this.filmPreload = { key: "", images: [] };
      this.camera.filmChapterIdx = null;
      this.camera.filmZoom = null;
      this.camera.filmZoomBase = null;
      this.camera.filmSetViewAt = 0;
      this.camera.filmFlyingUntil = 0;
      this.camera.filmLastCenter = null;
      this.camera.filmFramesSinceReset = 0;
      this.camera.filmLastBoat = null;
      this.camera.filmStillAnchor = null;
      const holdZoom = Number.isFinite(this.camera.filmZoomHold)
        ? this.camera.filmZoomHold
        : this.map?.getZoom?.();
      this.camera.filmZoomHold = null;
      this.map?.stop?.();
      this.camera.exitHoldZoom = Number.isFinite(holdZoom) ? holdZoom : this.map?.getZoom?.();
      this.camera.exitHold = true;
      this.camera.exitHoldUntil = Date.now() + EXIT_HOLD_MS;
      this.camera.recapture = this.config.cinemaRecapture;
      this.camera.resetKey = `${this.config.view}-${this.config.sceneReady ? "ready" : "load"}-${this.config.cinemaRecapture}`;
      const live = this.config.live;
      if (live && Number.isFinite(live.lat) && Number.isFinite(live.lon) && this.map) {
        const lonCam = cameraLngForBoat(live.lon, this.camera.followLon);
        this.camera.followLon = lonCam;
        this.camera.lastPos = { lat: live.lat, lon: live.lon };
        const hold = Number.isFinite(this.camera.exitHoldZoom)
          ? this.camera.exitHoldZoom
          : this.map.getZoom();
        this.programmaticMove(() => this.map.setView(
          [live.lat, lonCam],
          hold,
          { animate: false },
        ));
        this.initialLive = { lat: live.lat, lon: live.lon };
      }
      window.clearTimeout(this.exitZoomTimer);
      this.exitZoomTimer = window.setTimeout(() => this.restoreExitZoom(), 180);
    }
    if (previousView && previousView !== this.config.view) this.resetCameraForView();
    this.syncBaseLayer();
    this.applyZoomFloor();
    this.syncInitialCamera();
    this.syncRoute();
    this.syncAltRoute();
    this.syncWaypoints();
    const playbackChanged = previous.flat !== this.config.flat
      || previous.marks !== this.config.marks
      || previous.boatKnots !== this.config.boatKnots
      || previous.routeReady !== this.config.routeReady
      || previous.stopAuto !== this.config.stopAuto
      || previous.filmActive !== this.config.filmActive;
    if (playbackChanged) {
      this.playback.configure({
        flat: this.config.flat,
        marks: this.config.marks,
        boatKnots: this.config.boatKnots,
        enabled: this.config.routeReady,
        stopAuto: this.config.stopAuto,
        filmActive: this.config.filmActive,
      });
    } else if (this.currentPlayback) {
      this.renderDynamic(this.currentPlayback);
    }
    if (this.config.filmActive) this.ensureFilmCameraLoop();
    // Entering / leaving the drawing mode: the boats of the official
    // route hide or come back at once, even while playback is paused.
    if (previous.drawingMode !== this.config.drawingMode || previous.sceneReady !== this.config.sceneReady) {
      this.syncMarkers(this.currentCast, this.currentPlayback);
    }
    if (!previous.drawingMode && this.config.drawingMode) {
      this.liftBoundsForDrawing();
      this.showWorld({ keepBoundsLifted: true });
    }
    if (previous.drawingMode && !this.config.drawingMode) {
      if (this._worldLockUntil && Date.now() < this._worldLockUntil) {
        this.liftBoundsForDrawing();
      } else {
        this.map?.setMaxBounds?.(this.boundsBeforeDraw || MAP_MAX_BOUNDS);
        this.boundsBeforeDraw = null;
        this._worldLockUntil = 0;
      }
    }
    if (
      !this._enforcingWorld
      && this.config.drawingMode
      && this._worldLockUntil
      && Date.now() < this._worldLockUntil
      && !this.userNavigated
      && this.map
      && this.map.getZoom() - this.sceneWorldZoom() > 0.05
    ) {
      this._enforcingWorld = true;
      try {
        this.showWorld({ keepBoundsLifted: true });
      } finally {
        this._enforcingWorld = false;
      }
    }
  }

  syncBaseLayer() {
    const url = this.config.isLightMode ? TILE_URLS.light : TILE_URLS.dark;
    const lang = this.config.lang === "en" ? "en" : "fr";
    const attr = tileAttribution(lang);
    if (this.config.filmActive) {
      if (!this.baseLayer) this.switchBaseLayer(url, attr);
      else if (this.baseLayer._naviguideAttr !== attr) this.switchBaseLayer(url, attr);
      return;
    }
    this.switchBaseLayer(url, attr);
  }

  /** Ré-ajoute avant de retirer : jamais une carte sans tuiles. */
  switchBaseLayer(url, attr) {
    const credit = attr || tileAttribution(this.config.lang === "en" ? "en" : "fr");
    if (this.baseLayer?._naviguideUrl === url && this.baseLayer?._naviguideAttr === credit) return;
    const next = bindQuietTiles(L.tileLayer(url, baseTileOptions(this.config.lang === "en" ? "en" : "fr")));
    next._naviguideUrl = url;
    next._naviguideAttr = credit;
    next.addTo(this.map);
    next.bringToBack();
    const prev = this.baseLayer;
    this.baseLayer = next;
    if (prev && prev !== next) prev.remove();
  }

  syncRoute() {
    const input = {
      segments: this.config.segments,
      customRoute: this.config.customRoute,
      drawingMode: this.config.drawingMode,
      drawnSegments: this.config.drawnSegments,
      sceneReady: this.config.sceneReady,
      flat: this.config.flat,
    };
    if (
      this.routeInputs
      && this.routeInputs.segments === input.segments
      && this.routeInputs.customRoute === input.customRoute
      && this.routeInputs.drawingMode === input.drawingMode
      && this.routeInputs.drawnSegments === input.drawnSegments
      && this.routeInputs.sceneReady === input.sceneReady
      && this.routeInputs.flat === input.flat
    ) return;
    this.routeInputs = input;
    const group = this.layers.update("route", () => L.layerGroup().addTo(this.map), (layer) => layer.clearLayers());
    // Une seule route à la fois : tracé en cours, perso ou Berry.
    const plan = routeDrawPlan(input);
    if (!plan.visible) return;
    if (plan.kind === "drawing") {
      (input.drawnSegments || []).filter(Boolean).forEach((segment) => {
        addRouteLine(group, segment.coords, {
          color: "#22c55e",
          weight: 3,
        });
      });
      return;
    }
    if (plan.kind === "custom") {
      input.customRoute.features
        .filter((feature) => feature.geometry?.type === "LineString")
        .forEach((feature) => addRouteLine(group, feature.geometry.coordinates, {
          color: "#0077ff",
          weight: ROUTE_MAIN_WEIGHT,
        }));
      return;
    }
    (input.segments || []).forEach((segment) => {
      if (!segment.coords?.length) return;
      const styles = officialAirRouteStyles(segment);
      if (!styles.length) return;
      styles.forEach((style) => addRouteLine(group, segment.coords, style));
    });
    const pts = input.flat?.points || [];
    const airStyles = officialAirRouteStyles({ air: true });
    for (let i = 0; i < pts.length - 1; i += 1) {
      if (!pts[i + 1].jump) continue;
      const coords = [
        [pts[i].lon, pts[i].lat],
        [pts[i + 1].lon, pts[i + 1].lat],
      ];
      airStyles.forEach((style) => addRouteLine(group, coords, style));
    }
    const sideStyles = officialAirRouteStyles({ side: true });
    for (const ep of input.flat?.episodes || []) {
      const coords = [];
      const hub = pts[ep.ja];
      if (hub) coords.push([hub.lon, hub.lat]);
      for (let i = ep.ja + 1; i < ep.jb; i += 1) {
        const p = pts[i];
        if (!p || p.jump) continue;
        coords.push([p.lon, p.lat]);
      }
      if (coords.length >= 2) {
        sideStyles.forEach((style) => addRouteLine(group, coords, style));
      }
    }
  }

  syncAltRoute() {
    const draft = this.config.draft;
    const showEnvelopes = Boolean(this.config.showEnvelopes);
    if (this.altDraft === draft && this.altShowEnvelopes === showEnvelopes) return;
    this.altDraft = draft;
    this.altShowEnvelopes = showEnvelopes;
    const group = this.layers.update("alt-route", () => L.layerGroup().addTo(this.map), (layer) => layer.clearLayers());
    if (!draft) return;
    const add = (coords, style) => {
      if (!coords?.length) return;
      addWorldLine(group, coords, { ...style, pane: "route" });
    };
    add(draft.old_geojson?.geometry?.coordinates, { color: "#94a3b8", weight: 2, dashArray: "7 7", opacity: 0.85 });
    add(draft.draft_geojson?.geometry?.coordinates, { color: "#22d3ee", weight: 3, opacity: 0.95 });
    if (showEnvelopes) {
      (draft.isochrones || []).forEach((iso) => {
        const ring = (iso || []).map((point) => [point.lon, point.lat]);
        if (ring.length > 2) add(ring, { color: "#fbbf24", weight: 1, dashArray: "2 4", opacity: 0.4 });
      });
    }
  }

  syncWake(sailNm, enabled) {
    const flat = this.config.flat;
    const group = this.layers.add("wake", () => L.layerGroup().addTo(this.map));
    if (!enabled || !flat?.points?.length) {
      if (this.wakeGeometry) group.clearLayers();
      this.wakeGeometry = null;
      return;
    }
    if (!this.wakeGeometry || this.wakeGeometry.flat !== flat) {
      group.clearLayers();
      const geometry = staticWakeParts(flat);
      geometry.flat = flat;
      const offsets = worldCopyOffsets(geometry.parts.flat());
      geometry.worldOffsets = offsets;
      geometry.parts.forEach((part) => {
        if (part.length < 2) return;
        offsets.forEach((offset) => L.polyline(latLngs(part, offset), REST_STYLE).addTo(group));
      });
      geometry.doneLines = geometry.parts.map(() => createWorldLines(group, WAKE_STYLE, offsets));
      geometry.tailLines = createWorldLines(group, WAKE_STYLE, offsets);
      geometry.completedIndex = -1;
      this.wakeGeometry = geometry;
    }
    const geometry = this.wakeGeometry;
    const target = Math.max(0, Number(sailNm) || 0);
    const targetIndex = wakeCursorAt({ points: geometry.points }, target, geometry.completedIndex);
    if (targetIndex < geometry.completedIndex) {
      clearDoneLines(geometry.doneLines);
      geometry.completedIndex = -1;
    }
    while (geometry.completedIndex < targetIndex) {
      geometry.completedIndex += 1;
      appendDonePoint(geometry, geometry.completedIndex);
    }
    const previous = geometry.points[geometry.completedIndex];
    const following = geometry.points[geometry.completedIndex + 1];
    const samePart = previous
      && following
      && geometry.partByPoint[geometry.completedIndex] === geometry.partByPoint[geometry.completedIndex + 1];
    const live = this.config.live;
    const pose = this.config.filmActive ? this.filmPose : null;
    const pin = pose && Number.isFinite(pose.lat) && Number.isFinite(pose.lon)
      ? pose
      : (this.config.filmActive && live && Number.isFinite(live.lat) && Number.isFinite(live.lon) ? live : null);
    const filmPin = Boolean(this.config.filmActive && pin);
    if (filmPin && previous && (!following || !following.jump)) {
      setWakeTail(geometry.tailLines, previous, {
        lon: unwrapLon(previous.lon, pin.lon),
        lat: pin.lat,
      }, geometry.worldOffsets);
      return;
    }
    if (!previous || !following || following.jump || !samePart) {
      setWakeTail(geometry.tailLines, null, null, geometry.worldOffsets);
      return;
    }
    const span = (following.cumNm ?? 0) - (previous.cumNm ?? 0);
    const ratio = span > 0 ? Math.max(0, Math.min(1, (target - (previous.cumNm ?? 0)) / span)) : 0;
    const followingLon = unwrapLon(previous.lon, following.lon);
    setWakeTail(geometry.tailLines, previous, {
      lon: previous.lon + ratio * (followingLon - previous.lon),
      lat: previous.lat + ratio * (following.lat - previous.lat),
    }, geometry.worldOffsets);
  }

  syncMarker(role, {
    visible,
    lat,
    lon,
    bearing,
    className,
    html,
    draggable = false,
  }) {
    let markers = this.markerSets.get(role) || [];
    if (!visible || lat == null || lon == null) {
      markers.forEach((marker) => marker.remove());
      this.markerSets.set(role, []);
      this.markerPrimaryLngs.delete(role);
      return;
    }
    // Pendant l'animation de zoom, Leaflet transforme les icônes en CSS ; un setLatLng calculé sur
    // l'ancienne projection les fait glisser (et, en film, sauter de copie monde — RG15).
    // On garde l'image ; zoomend + la boucle film reposent le bateau.
    if (this.zoomAnimating && markers.length) return;
    const cam = this.map.getCenter()?.lng;
    const primary = stabilizeWorldLng(lon, cam, this.markerPrimaryLngs.get(role));
    this.markerPrimaryLngs.set(role, primary);
    const lngs = [primary, ...markerCopyLngs(lon).filter((lng) => Math.abs(lng - primary) > 1e-6)];
    const byKey = new Map();
    for (const marker of markers) {
      byKey.set(worldCopyKey(lon, marker.getLatLng()?.lng), marker);
    }
    const next = [];
    for (const [index, lng] of lngs.entries()) {
      const copyKey = worldCopyKey(lon, lng);
      const isPrimary = index === 0;
      let marker = byKey.get(copyKey);
      if (!marker) {
        marker = L.marker([lat, lng], {
          icon: markerIcon(className, html),
          draggable: draggable && isPrimary,
          pane: "boat",
          interactive: draggable && isPrimary,
        }).addTo(this.map);
        if (draggable && isPrimary) {
          marker.on("dragstart", () => {
            this.playback.pause();
            this.callbacks.onBoatDragStart?.();
          });
          marker.on("drag", (event) => {
            const point = event.target.getLatLng();
            this.callbacks.onBoatDrag?.({ lat: point.lat, lon: wrapLon(point.lng) });
          });
        }
      } else {
        byKey.delete(copyKey);
        marker.setLatLng([lat, lng]);
      }
      applyMarkerRotation(marker, bearing || 0);
      next.push(marker);
    }
    byKey.forEach((marker) => marker.remove());
    this.markerSets.set(role, next);
    this.eventBubble?.sync();
  }

  syncMarkers(cast, snapshot) {
    const cfg = this.config;
    const ready = Boolean(cfg.sceneReady && !cfg.drawingMode);
    const liveMode = cfg.isSuivre && cfg.live && !cfg.previewing;
    // `visible` after the spread: a cast actor carries its own `visible`
    // flag, which used to override ours (ghost boats in Simulation, boats
    // left on the map while drawing — revue du 19 sept.).
    this.syncMarker("simulation", {
      ...cast?.main,
      visible: ready && cfg.isTracer && Boolean(cast?.main),
      className: "catamaran-divicon",
      html: catamaranSvg(0),
      draggable: true,
    });
    const filmFollow = cfg.filmActive ? (this.filmPose || cast?.follow) : null;
    const episodeParked = cast?.vehicle === "plane" || cast?.vehicle === "side"
      || cfg.live?.vehicle === "side" || cfg.live?.vehicle === "plane";
    const parkLat = cast?.main?.lat ?? cfg.live?.parkLat;
    const parkLon = cast?.main?.lon ?? cfg.live?.parkLon;
    this.syncMarker("live", {
      visible: ready && liveMode && (episodeParked ? Number.isFinite(parkLat) : cast?.vehicle !== "plane"),
      lat: episodeParked ? parkLat : (filmFollow?.lat ?? cfg.live?.lat),
      lon: episodeParked ? parkLon : (filmFollow?.lon ?? cfg.live?.lon),
      bearing: episodeParked
        ? (cast?.main?.bearing ?? cfg.live?.bearing ?? 0)
        : (filmFollow?.heading ?? filmFollow?.bearing ?? cfg.live?.bearing ?? 0),
      className: "catamaran-divicon catamaran-divicon--live",
      html: catamaranSvg(0),
    });
    this.syncMarker("ghost", {
      ...cast?.main,
      visible: ready && cfg.isSuivre && cfg.previewing && Boolean(cast?.main),
      className: "catamaran-divicon catamaran-divicon--ghost",
      html: catamaranSvg(0),
    });
    const liveIsSide = cfg.live?.vehicle === "side";
    this.syncMarker("side", {
      ...cast?.side,
      visible: ready && (Boolean(cast?.side?.visible) || (liveMode && liveIsSide && !cfg.filmActive)),
      lat: cast?.side?.visible ? cast.side.lat : (liveIsSide ? cfg.live?.lat : cast?.side?.lat),
      lon: cast?.side?.visible ? cast.side.lon : (liveIsSide ? cfg.live?.lon : cast?.side?.lon),
      bearing: cast?.side?.visible ? cast.side.bearing : (liveIsSide ? cfg.live?.bearing : cast?.side?.bearing),
      className: "catamaran-divicon catamaran-divicon--side",
      html: catamaranSvg(0),
    });
    this.syncMarker("plane", {
      ...cast?.plane,
      visible: ready && Boolean(cast?.plane?.visible),
      className: "plane-divicon",
      html: planeHtml(),
    });
    const drawBoat = cfg.drawnSegments?.length >= 1 ? cfg.drawnPoints?.at(-1) : null;
    this.syncMarker("drawing", {
      ...drawBoat,
      visible: Boolean(cfg.drawingMode && drawBoat),
      bearing: 0,
      className: "catamaran-divicon catamaran-divicon--draw",
      html: catamaranSvg(0),
    });
    this.eventBubble?.sync();
  }

  syncAirHop(cast) {
    const visible = isAirPhase(cast?.phase);
    if (!visible || !cast?.hopFrom || !cast?.hopTo) {
      this.layers.remove("air-hop");
      return;
    }
    const group = this.layers.add("air-hop", () => L.layerGroup().addTo(this.map));
    const copies = worldCopyLineCoords([
      [cast.hopFrom.lon, cast.hopFrom.lat],
      [cast.hopTo.lon, cast.hopTo.lat],
    ]);
    const air = officialRouteLineStyle({ air: true });
    const style = {
      color: air.color,
      weight: air.weight,
      dashArray: air.dash,
      opacity: 0.95,
      pane: "route",
      interactive: false,
    };
    const lines = group.getLayers();
    if (lines.length !== copies.length) {
      group.clearLayers();
      copies.forEach((copy) => L.polyline(
        copy.map(([lon, lat]) => [lat, lon]),
        style,
      ).addTo(group));
      return;
    }
    lines.forEach((line, index) => {
      line.setLatLngs(copies[index].map(([lon, lat]) => [lat, lon]));
    });
  }

  syncWaypoints() {
    const cfg = this.config;
    if (this.zoomAnimating && this.waypointMarkers.size) {
      // Drapeaux : mêmes glissements pendant l'animation de zoom ; onZoomEnd replanifie.
      this.waypointsDirty = true;
      return;
    }
    // Brouillon vide : drapeaux Berry (Ajaccio). Dès le
    // premier point, seuls les ronds de tracé. Le clic fiche n'est un
    // clic « dessin » que s'il y a déjà un point.
    const drawingHasPoints = Boolean(cfg.drawingMode && (cfg.drawnPoints || []).length);
    const source = drawingHasPoints
      ? (cfg.drawnPoints || []).map((point, index) => ({ ...point, name: point.name || `${index + 1}`, flag: "", flags: [] }))
      : (cfg.customRoute ? [] : (cfg.points || []));
    const inputs = {
      source,
      points: cfg.points,
      drawnPoints: cfg.drawnPoints,
      drawingMode: cfg.drawingMode,
      customRoute: cfg.customRoute,
      segments: cfg.segments,
    };
    if (
      !this.waypointsDirty
      && this.waypointInputs
      && this.waypointInputs.points === inputs.points
      && this.waypointInputs.drawnPoints === inputs.drawnPoints
      && this.waypointInputs.drawingMode === inputs.drawingMode
      && this.waypointInputs.customRoute === inputs.customRoute
      && this.waypointInputs.segments === inputs.segments
    ) return;
    this.waypointInputs = inputs;
    this.waypointsDirty = false;
    const sourceStamp = source.map((point) => `${point.lat}:${point.lon}`).join("|");
    if (this.waypointSourceStamp !== sourceStamp) {
      this.waypointSourceStamp = sourceStamp;
      this.waypointLastOffsets = [];
      this.waypointPrimaryLngs = new Map();
    }
    const routeCoords = (cfg.segments || []).filter((segment) => !segment.nonMaritime).flatMap((segment) => segment.coords || []);
    const project = (lon, lat) => {
      const point = this.map.latLngToLayerPoint([lat, lon]);
      return { x: point.x, y: point.y };
    };
    const offsets = source.length
      ? computeMarkerOffsets(source, project, projectRouteSegments(routeCoords, project), this.waypointLastOffsets)
      : [];
    this.waypointLastOffsets = offsets;
    const group = this.layers.add("waypoints", () => L.layerGroup().addTo(this.map));
    const expected = new Set();
    const bounds = this.map.getBounds();
    const west = bounds.getWest();
    const east = bounds.getEast();
    const cameraLng = this.map.getCenter()?.lng;
    source.forEach((point, index) => {
      const srcs = waypointFlagSrcs(point);
      if (!srcs.length && !drawingHasPoints) return;
      const offset = offsets[index] || [0, 0];
      const stamp = ` data-testid="waypoint-flag" data-escale="${String(point.name || "").replace(/"/g, "&quot;")}"`;
      const html = srcs.length
        ? flagMarkerHtml(srcs, [0, 0]).replace("<div ", `<div${stamp} `)
        : drawingPinHtml(index, stamp);
      const metrics = srcs.length ? flagIconMetrics(srcs) : drawingPinMetrics();
      const iconAnchor = srcs.length ? offsetToIconAnchor(metrics.iconAnchor, offset) : metrics.iconAnchor;
      const lngs = [];
      const seen = new Set();
      const addLng = (lng) => {
        if (!Number.isFinite(lng)) return;
        const key = lng.toFixed(5);
        if (seen.has(key)) return;
        seen.add(key);
        lngs.push(lng);
      };
      const primary = stabilizeWorldLng(point.lon, cameraLng, this.waypointPrimaryLngs.get(index));
      this.waypointPrimaryLngs.set(index, primary);
      addLng(primary);
      for (const lng of markerCopyLngs(point.lon)) {
        if (lng >= west - 60 && lng <= east + 60) addLng(lng);
      }
      for (const lng of worldCopyLngs(point.lon)) {
        if (lng >= west - 60 && lng <= east + 60) addLng(lng);
      }
      for (const lng of lngs) {
        const key = `${cfg.drawingMode ? "draw" : "route"}:${index}:${worldCopyKey(point.lon, lng)}`;
        expected.add(key);
        const iconKey = `${html}|${metrics.iconSize.join(",")}|${iconAnchor.join(",")}`;
        let icon = this.divIconCache.get(iconKey);
        if (!icon) {
          icon = L.divIcon({
            className: "flag-divicon",
            html,
            iconSize: metrics.iconSize,
            iconAnchor,
          });
          this.divIconCache.set(iconKey, icon);
        }
        let marker = this.waypointMarkers.get(key);
        if (!marker) {
          marker = L.marker([point.lat, lng], {
            icon,
            interactive: true,
          }).addTo(group);
          marker.on("mouseover", () => this.callbacks.onWaypointHover?.(marker._naviguideWaypoint));
          marker.on("mouseout", () => this.callbacks.onWaypointHover?.(null));
          marker.on("click", (event) => {
            L.DomEvent.stopPropagation(event);
            if (marker._naviguideDrawing) {
              this.callbacks.onDrawingWaypointClick?.(marker._naviguideWaypoint, marker._naviguideIndex);
              return;
            }
            this.callbacks.onWaypointClick?.(marker._naviguideWaypoint, marker._naviguideIndex);
          });
          this.waypointMarkers.set(key, marker);
        }
        marker._naviguideWaypoint = point;
        marker._naviguideDrawing = drawingHasPoints;
        marker._naviguideIndex = index;
        marker.setLatLng([point.lat, lng]);
        if (marker._naviguideIconKey !== iconKey) {
          marker.setIcon(icon);
          marker._naviguideIconKey = iconKey;
        }
      }
    });
    this.waypointMarkers.forEach((marker, key) => {
      if (expected.has(key)) return;
      group.removeLayer(marker);
      this.waypointMarkers.delete(key);
    });
    this.escalePopup?.sync();
  }

  /** The camera is driving the map: playback running, or the live boat followed. */
  isCameraFollowing() {
    const cfg = this.config || {};
    if (cfg.filmActive) return true;
    if (!cfg.cameraFollow) return false;
    const liveMode = Boolean(cfg.isSuivre && cfg.live && !cfg.previewing);
    return Boolean(this.currentPlayback?.playing || liveMode);
  }

  scheduleWaypoints({ reason = "move" } = {}) {
    if (!this.config.points?.length && !this.config.drawnPoints?.length) return;
    if (reason === "follow") return; // flags stay put while the camera follows
    if (this.zoomAnimating && reason !== "zoom") return;
    if (reason === "zoom") {
      window.clearTimeout(this.waypointTimer);
      this.waypointsDirty = true;
      this.syncWaypoints();
      this.syncDynamicWorldCopies();
      return;
    }
    if (this.config?.filmActive) return; // flags stay put for the whole film sauf zoom
    window.clearTimeout(this.waypointTimer);
    this.waypointTimer = window.setTimeout(() => {
      this.waypointsDirty = true;
      this.syncWaypoints();
    }, markerOffsetDelay(this.config.cameraFollow, reason));
  }

  /** Bateau au centre, zoom = plancher de Suivre. */
  frameFollowLive(live) {
    const applied = applyFollowCadrage(this.map, live, {
      followLon: this.camera.followLon,
      minZoom: MAP_MIN_ZOOM,
      move: (fn) => this.programmaticMove(fn),
    });
    if (!applied) return;
    this.camera.followLon = applied.followLon;
    this.initialLive = { lat: live.lat, lon: live.lon };
    this._pendingFollowCadrage = false;
    this._followFramed = true;
  }

  syncInitialCamera() {
    const cfg = this.config;
    if (!cfg.routeReady || !cfg.flat?.points?.length) {
      this.setCameraPlaced(false);
      return;
    }
    if (cfg.filmActive) {
      this.setCameraPlaced(true);
      return;
    }
    if (this.camera.exitHold || Number.isFinite(this.camera.exitHoldZoom)) {
      if (cfg.isSuivre && cfg.live && Number.isFinite(cfg.live.lat)) {
        this.initialLive = { lat: cfg.live.lat, lon: cfg.live.lon };
        this._followFramed = true;
      }
      this.setCameraPlaced(true);
      return;
    }
    const recette = cfg.recetteMap;
    if (recette) {
      this.programmaticMove(() => this.map.setView([recette.lat, recette.lon], recette.z, { animate: false }));
      this.setCameraPlaced(true);
      return;
    }
    if (this.userNavigated) {
      // Un geste a déjà choisi la vue : on ne la reprend pas pour centrer le bateau.
      this._pendingFollowCadrage = false;
    } else if (cfg.isSuivre && !cfg.drawingMode && !this._followFramed) {
      this._pendingFollowCadrage = true;
    }
    const mayPlace = shouldPlaceInitialCamera({ userNavigated: this.userNavigated })
      || this._pendingFollowCadrage;
    if (mayPlace && shouldFrameFollowLive({
      isSuivre: cfg.isSuivre,
      filmActive: cfg.filmActive,
      drawingMode: cfg.drawingMode,
      live: cfg.live,
      userNavigated: this.userNavigated,
      initialLive: this.initialLive,
      pending: this._pendingFollowCadrage,
    })) {
      this.frameFollowLive(cfg.live);
    }
    this.setCameraPlaced(true);
  }

  sceneWorldZoom() {
    return worldViewZoom(this.map?.getSize(), this.map?.options?.zoomSnap, WORLD_ZOOM, MAP_MIN_ZOOM);
  }

  /**
   * Plancher de dézoom : un seul monde en Suivre, Simulation, film et Tracer.
   * Tracer pose la vue à ce plancher (monde entier, une fois).
   */
  applyZoomFloor() {
    if (!this.map?.setMinZoom) return;
    const floor = followMinZoom(this.map.getSize(), this.map.options.zoomSnap, MAP_MIN_ZOOM);
    if (this.map.options.minZoom === floor) return;
    // setMinZoom remonte la vue si elle est sous le plancher : mouvement de la carte, pas de l'utilisateur.
    this.programmaticMove(() => this.map.setMinZoom(floor));
  }

  /** Lève maxBounds et pose drawingMode avant showWorld. */
  liftBoundsForDrawing() {
    this.camera.exitHoldZoom = null;
    this.camera.exitHold = false;
    this.boundsBeforeDraw = this.map?.options?.maxBounds || MAP_MAX_BOUNDS;
    this.map?.setMinZoom?.(followMinZoom(this.map?.getSize(), this.map?.options?.zoomSnap, MAP_MIN_ZOOM));
    this.map?.setMaxBounds?.(null);
  }

  /**
   * Entrée Tracer : drawingMode sur le contrôleur AVANT showWorld, pour
   * que le geste ne remette pas maxBounds (revue du 26 sept., zoom 3 Amériques).
   */
  beginDrawingWorld() {
    this._pendingDrawUntil = Date.now() + 2000;
    this._worldLockUntil = Date.now() + 2000;
    this.userNavigated = false;
    this.config = { ...this.config, drawingMode: true };
    this.liftBoundsForDrawing();
    this.showWorld({ keepBoundsLifted: true });
  }

  /** Berry / Annuler : lever le verrou 2 s pour afficher tout de suite la route Berry. */
  endDrawingWorld() {
    this._pendingDrawUntil = 0;
    this._worldLockUntil = 0;
  }

  /** Tracer / accueil : monde entier, même si maxBounds a relevé le plancher. */
  showWorld({ keepBoundsLifted = false } = {}) {
    if (!this.map) return;
    if (keepBoundsLifted || this.config.drawingMode) {
      this._worldLockUntil = Date.now() + 2000;
    }
    this.map.invalidateSize();
    const floor = followMinZoom(this.map.getSize(), this.map.options.zoomSnap, MAP_MIN_ZOOM);
    const worldZ = worldViewZoom(this.map.getSize(), this.map.options.zoomSnap, WORLD_ZOOM, MAP_MIN_ZOOM);
    this.map.setMinZoom(floor);
    this.programmaticMove(() => {
      const bounds = this.map.options.maxBounds;
      if (bounds) this.map.setMaxBounds(null);
      this.map.setView(WORLD_CENTER, worldZ, { animate: false });
      const leaveLifted = keepBoundsLifted || this.config.drawingMode;
      if (!leaveLifted && bounds) {
        this.map.setMaxBounds(bounds);
        if (this.map.getZoom() - worldZ > 0.05) {
          this.map.setMaxBounds(null);
          this.map.setView(WORLD_CENTER, worldZ, { animate: false });
        }
      }
      if (this.map.getZoom() - worldZ > 0.05) {
        this.map.setMaxBounds(null);
        this.map.setMinZoom(floor);
        this.map.setView(WORLD_CENTER, worldZ, { animate: false });
      }
    });
  }

  resetCameraForView() {
    this.initialLive = null;
    this.userNavigated = false;
    this._followFramed = false;
    this._pendingFollowCadrage = Boolean(this.config.isSuivre);
    this.cameraPlaced = false;
    this.camera = {
      lastFollow: 0,
      lastJump: 0,
      lastPos: null,
      followLon: null,
      lastPhase: null,
      resetKey: null,
      recapture: null,
      focus: null,
      filmChapterIdx: null,
      filmZoom: null,
      filmZoomBase: null,
      filmSetViewAt: 0,
      filmFlyingUntil: 0,
      filmLastCenter: null,
      filmFramesSinceReset: 0,
      filmLastBoat: null,
      filmStillAnchor: null,
      filmZoomHold: null,
      exitHold: false,
      exitHoldUntil: null,
      exitHoldZoom: null,
    };
    this.stopFilmCameraLoop();
    this.filmSamples = [];
    this.filmPose = null;
    this.filmPreload = { key: "", images: [] };
  }

  setCameraPlaced(next) {
    if (this.cameraPlaced === next) return;
    this.cameraPlaced = next;
    this.callbacks.onCameraPlaced?.(next);
  }

  /**
   * Zoom de sortie du film : tenu quelques instants seulement (le temps qu'un dernier flyTo du film se pose),
   * puis relâché. Avant le 27 sept. il n'était jamais relâché : onZoomEnd le ré-imposait à chaque zoom.
   */
  restoreExitZoom() {
    const hold = this.camera?.exitHoldZoom;
    if (!Number.isFinite(hold) || this.config.filmActive || this.config.drawingMode || !this.map) return;
    if (Number.isFinite(this.camera.exitHoldUntil) && Date.now() > this.camera.exitHoldUntil) {
      this.releaseExitZoom();
      return;
    }
    const z = this.map.getZoom();
    if (Math.abs(z - hold) <= 0.05) return;
    this.programmaticMove(() => this.map.setView(this.map.getCenter(), hold, { animate: false }));
  }

  releaseExitZoom() {
    if (!this.camera) return;
    this.camera.exitHold = false;
    this.camera.exitHoldZoom = null;
    this.camera.exitHoldUntil = null;
    window.clearTimeout(this.exitZoomTimer);
  }

  programmaticMove(fn) {
    this.ignoreUserNavigation = true;
    window.clearTimeout(this.ignoreUserNavigationTimer);
    this.ignoreUserNavigationTimer = window.setTimeout(() => {
      this.ignoreUserNavigation = false;
    }, 120);
    fn();
  }

  ensureFilmCameraLoop() {
    if (this.filmLoopRaf) return;
    const tick = (now) => {
      if (!this.config.filmActive) {
        this.filmLoopRaf = 0;
        return;
      }
      this.syncFilmCamera(this.config, now);
      this.renderDynamic(this.currentPlayback || this.playback.snapshot());
      this.filmLoopRaf = requestAnimationFrame(tick);
    };
    this.filmLoopRaf = requestAnimationFrame(tick);
  }

  stopFilmCameraLoop() {
    if (this.filmLoopRaf) cancelAnimationFrame(this.filmLoopRaf);
    this.filmLoopRaf = 0;
  }

  ensureFilmTiles(leg, zoom) {
    const z = Math.round(Number(zoom));
    const key = `${z}:${leg?.fromLat}:${leg?.fromLon}:${leg?.toLat}:${leg?.toLon}`;
    if (!leg || !Number.isFinite(z) || this.filmPreload.key === key) return;
    const template = this.baseLayer?._url || TILE_URLS.dark;
    this.filmPreload = {
      key,
      images: preloadFilmTiles(template, tilesAlongLeg(leg, z)),
    };
  }

  syncFilmCamera(cfg, now = (typeof performance !== "undefined" ? performance.now() : Date.now())) {
    const film = typeof window !== "undefined" ? window.__naviguideFilm : null;
    const follow = this.currentCast?.follow;
    const subject = {
      lat: Number.isFinite(film?.lat) ? film.lat
        : (Number.isFinite(follow?.lat) ? follow.lat : cfg.live?.lat),
      lon: Number.isFinite(film?.lon) ? film.lon
        : (Number.isFinite(follow?.lon) ? follow.lon : cfg.live?.lon),
      heading: film?.heading ?? film?.bearing ?? follow?.bearing ?? cfg.live?.bearing,
    };
    if (!subject || !Number.isFinite(subject.lat) || !Number.isFinite(subject.lon)) return;
    const lonCam = stabilizeWorldLng(subject.lon, this.map.getCenter()?.lng, this.camera.followLon);
    this.camera.followLon = lonCam;
    const chapterIdx = Number.isFinite(Number(cfg.filmChapterIdx))
      ? Number(cfg.filmChapterIdx)
      : (Number.isFinite(Number(film?.chapterIdx)) ? Number(film.chapterIdx) : 0);
    const last = this.filmSamples[this.filmSamples.length - 1];
    const moved = !last
      || Math.abs(last.lat - subject.lat) > 1e-7
      || Math.abs(last.lon - lonCam) > 1e-7
      || last.chapterIdx !== chapterIdx;
    if (moved) {
      pushFilmSample(this.filmSamples, {
        t: now,
        lat: subject.lat,
        lon: lonCam,
        heading: subject.heading,
        chapterIdx,
        filmNm: Number.isFinite(Number(film?.filmNm)) ? Number(film.filmNm) : Number(cfg.live?.filmNm),
      });
    }
    const holdZ = this.camera.filmZoomHold;
    const zoomHeld = Number.isFinite(holdZ);
    if (!zoomHeld && (this.camera.filmZoomBase == null || this.camera.filmChapterIdx !== chapterIdx)) {
      this.camera.filmZoomBase = filmChapterZoom(this.map, cfg.filmLeg);
      if (this.camera.filmZoom == null) this.camera.filmZoom = this.camera.filmZoomBase;
      this.ensureFilmTiles(cfg.filmLeg, this.camera.filmZoomBase);
    }
    const tilesReady = filmTilesReady(this.map, this.baseLayer);
    let next;
    this.programmaticMove(() => {
      next = stepFilmCamera(this.map, {
        samples: this.filmSamples,
        now,
        lastChapterIdx: this.camera.filmChapterIdx,
        lastSetViewAt: this.camera.filmSetViewAt || 0,
        flyingUntil: this.camera.filmFlyingUntil || 0,
        lastCenter: this.camera.filmLastCenter,
        zoom: zoomHeld ? holdZ : this.camera.filmZoom,
        baseZoom: zoomHeld ? holdZ : this.camera.filmZoomBase,
        tilesReady,
        chapterIdx,
        filmLeg: zoomHeld ? null : cfg.filmLeg,
        lastBoat: this.camera.filmLastBoat,
        framesSinceReset: this.camera.filmFramesSinceReset || 0,
        stillAnchor: this.camera.filmStillAnchor,
      });
    });
    if (!next || next.action === "idle") return;
    const pose = next.pose;
    if (pose) {
      this.filmPose = {
        ...pose,
        lon: stabilizeWorldLng(pose.lon, lonCam, this.markerPrimaryLngs.get("live") ?? lonCam),
        heading: pose.heading,
      };
      this.camera.filmLastBoat = { lat: pose.lat, lon: pose.lon };
    }
    this.camera.filmChapterIdx = next.lastChapterIdx;
    this.camera.filmSetViewAt = next.lastSetViewAt;
    this.camera.filmFlyingUntil = next.flyingUntil || 0;
    this.camera.filmLastCenter = next.lastCenter ?? this.camera.filmLastCenter;
    this.camera.filmFramesSinceReset = next.framesSinceReset ?? 0;
    this.camera.filmStillAnchor = next.stillAnchor ?? null;
    if (zoomHeld) this.camera.filmZoom = holdZ;
    else if (Number.isFinite(Number(next.zoom))) this.camera.filmZoom = Number(next.zoom);
    else if (pose) this.camera.filmZoom = this.camera.filmZoom;
    this.camera.lastFollow = Date.now();
    if (this.filmPose) this.syncFilmBoat(this.filmPose);
  }

  syncFilmBoat(pose) {
    const cfg = this.config;
    if (!cfg.filmActive || !pose) return;
    const veh = this.currentCast?.vehicle;
    if (veh === "plane" || veh === "side") return;
    const ready = Boolean(cfg.sceneReady && !cfg.drawingMode);
    const liveMode = cfg.isSuivre && cfg.live && !cfg.previewing;
    this.syncMarker("live", {
      visible: ready && liveMode && veh !== "plane",
      lat: pose.lat,
      lon: pose.lon,
      bearing: pose.heading || 0,
      className: "catamaran-divicon catamaran-divicon--live",
      html: catamaranSvg(0),
    });
  }

  filmPlayheadNm(snapshot) {
    if (!this.config.filmActive) return snapshot?.nm;
    const fromPose = Number(this.filmPose?.filmNm);
    if (Number.isFinite(fromPose)) return fromPose;
    const film = typeof window !== "undefined" ? window.__naviguideFilm : null;
    const fromFilm = Number(film?.filmNm);
    if (Number.isFinite(fromFilm)) return fromFilm;
    const fromLive = Number(this.config.live?.filmNm);
    if (Number.isFinite(fromLive)) return fromLive;
    return snapshot?.nm;
  }

  syncCamera(cast, snapshot) {
    const cfg = this.config;
    if (cfg.filmActive || cfg.drawingMode) return;
    const liveMode = cfg.isSuivre && cfg.live && !cfg.previewing;
    const subject = liveMode ? cfg.live : cast?.follow;
    const enabled = Boolean(
      cfg.sceneReady
      && (
        (cfg.cameraFollow && (cast?.follow || liveMode))
        || (cfg.isTracer && cfg.cameraFocusToken > 0 && cast?.follow)
      )
      && subject?.lat != null
      && subject?.lon != null,
    );
    if (!enabled) return;
    const resetKey = `${cfg.view}-${cfg.sceneReady ? "ready" : "load"}-${cfg.cinemaRecapture}`;
    if (this.camera.resetKey !== resetKey) {
      this.camera.lastFollow = 0;
      this.camera.lastJump = 0;
      this.camera.lastPos = null;
      this.camera.followLon = null;
      this.camera.lastPhase = null;
      this.camera.focus = cfg.cameraFocusToken;
      this.camera.resetKey = resetKey;
    }
    const lonCam = cameraLngForBoat(subject.lon, this.camera.followLon);
    this.camera.followLon = lonCam;
    const holdAlive = Number.isFinite(this.camera.exitHoldZoom)
      && Number.isFinite(this.camera.exitHoldUntil)
      && Date.now() <= this.camera.exitHoldUntil;
    if (holdAlive) {
      this.camera.recapture = cfg.cinemaRecapture;
      const hold = this.camera.exitHoldZoom;
      this.programmaticMove(() => this.map.setView([subject.lat, lonCam], hold, { animate: false }));
      this.camera.lastPos = { lat: subject.lat, lon: subject.lon };
      this.camera.lastFollow = Date.now();
      return;
    }
    if (Number.isFinite(this.camera.exitHoldZoom) && cfg.cinemaRecapture !== this.camera.recapture) {
      this.camera.exitHoldZoom = null;
      this.camera.exitHold = false;
    }
    const previous = this.camera.lastPos;
    const movedNm = previous ? haversineNm(previous.lat, previous.lon, subject.lat, subject.lon) : 0;
    this.camera.lastPos = { lat: subject.lat, lon: subject.lon };
    const zoom = liveMode
      ? cadrageZoom(this.map?.getSize(), this.map?.options?.zoomSnap, MAP_MIN_ZOOM)
      : zoomForRemaining(cfg.remainingNm ?? snapshot.sailTotalNm);
    const tokenJump = !liveMode && snapshot.jumpToken && snapshot.jumpToken !== this.camera.lastJump;
    if (tokenJump) this.camera.lastJump = snapshot.jumpToken;
    const phaseChanged = cast?.phase && cast.phase !== this.camera.lastPhase;
    if (cast?.phase) this.camera.lastPhase = cast.phase;
    const recapture = cfg.cinemaRecapture !== this.camera.recapture;
    if (recapture) this.camera.recapture = cfg.cinemaRecapture;
    const focus = cfg.cameraFocusToken !== this.camera.focus;
    if (focus) this.camera.focus = cfg.cameraFocusToken;
    if (isAirPhase(cast?.phase) && cast?.hopFrom && cast?.hopTo) {
      if (cfg.cameraFollow && (phaseChanged || tokenJump || recapture)) {
        const lonA = cameraLngForBoat(cast.hopFrom.lon, this.camera.followLon);
        const lonB = cameraLngForBoat(cast.hopTo.lon, lonA);
        this.camera.followLon = lonB;
        this.programmaticMove(() => this.map.fitBounds(
          [[cast.hopFrom.lat, lonA], [cast.hopTo.lat, lonB]],
          { padding: [72, 96], maxZoom: 3.15, animate: true, duration: 0.9 },
        ));
        this.camera.lastFollow = Date.now();
        this.camera.lastPos = null;
      }
      return;
    }
    if (focus) {
      this.programmaticMove(() => this.map.setView([subject.lat, lonCam], this.map.getZoom(), { animate: false }));
      this.camera.lastFollow = Date.now();
      return;
    }
    if (recapture || previous == null) {
      if (cfg.isSuivre) {
        this._pendingFollowCadrage = true;
        if (liveMode) {
          this.frameFollowLive(subject);
        } else {
          const z = cadrageZoom(this.map?.getSize(), this.map?.options?.zoomSnap, MAP_MIN_ZOOM);
          const here = this.map.getCenter();
          this.programmaticMove(() => this.map.setView([here.lat, here.lng], z, { animate: false }));
        }
      } else {
        this.programmaticMove(() => this.map.setView([subject.lat, lonCam], zoom, { animate: false }));
      }
      this.camera.lastFollow = Date.now();
      return;
    }
    if (!cfg.cameraFollow || (!liveMode && !snapshot.playing)) return;
    if (tokenJump || phaseChanged || movedNm >= TELEPORT_NM) {
      this.programmaticMove(() => this.map.flyTo(
        [subject.lat, lonCam],
        zoom,
        { duration: movedNm >= TELEPORT_NM || phaseChanged ? 0.7 : 1.05 },
      ));
      this.camera.lastFollow = Date.now();
      return;
    }
    const now = Date.now();
    if (now - this.camera.lastFollow < 700) return;
    this.camera.lastFollow = now;
    const currentZoom = this.map.getZoom();
    this.programmaticMove(() => this.map.setView(
      [subject.lat, lonCam],
      Math.abs(currentZoom - zoom) >= 1.25 ? zoom : currentZoom,
      { animate: true, duration: 0.55 },
    ));
  }

  renderDynamic(snapshot) {
    this.currentPlayback = snapshot;
    const cast = interpolateCast(this.config.flat, this.filmPlayheadNm(snapshot), { stops: this.config.stops });
    this.currentCast = cast;
    const liveMode = this.config.isSuivre && this.config.live && !this.config.previewing;
    const sailNm = liveMode ? (this.config.live.sailNm ?? 0) : (cast?.sailNm ?? 0);
    this.syncWake(sailNm, this.config.sceneReady && !this.config.drawingMode && !this.config.customRoute);
    this.syncMarkers(cast, snapshot);
    this.syncAirHop(cast);
    this.syncCamera(cast, snapshot);
  }

  syncDynamicWorldCopies() {
    if (!this.currentPlayback) return;
    this.syncMarkers(this.currentCast, this.currentPlayback);
  }

  publishPlayback(snapshot) {
    this.callbacks.onPlayback?.({ ...snapshot, cast: this.currentCast });
  }

  dispose() {
    this.stopFilmCameraLoop();
    this.eventBubble?.dispose();
    this.eventBubble = null;
    this.escalePopup?.dispose();
    this.escalePopup = null;
    this.clearBriefingFocus();
    window.clearTimeout(this.waypointTimer);
    window.clearTimeout(this.ignoreUserNavigationTimer);
    window.clearTimeout(this.exitZoomTimer);
    this.playback.destroy();
    this.map.off("zoomanim", this.onZoomAnim);
    this.map.off("zoomend", this.onZoomEnd);
    this.map.off("moveend", this.onMoveEnd);
    this.map.off("zoomstart", this.onUserNavigation);
    this.map.off("resize", this.onResize);
    this.map.off("dragstart", this.onUserNavigation);
    this.layers.clear();
    this.markerSets.forEach((markers) => markers.forEach((marker) => marker.remove()));
    this.markerSets.clear();
    this.waypointMarkers.clear();
    this.divIconCache.clear();
    this.baseLayer?.remove();
    this.releaseCompactAttribution?.();
    this.map.remove();
  }
}
