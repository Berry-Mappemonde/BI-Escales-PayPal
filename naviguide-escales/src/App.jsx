import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Redo2, Undo2, X } from "lucide-react";
import { Sidebar } from "./components/Sidebar.jsx";
import { PanelBoundary, ReplayErrorBoundary } from "./components/RootErrorBoundary.jsx";
import { CarnetDeBord, mapPageHref, useCarnetPage } from "./components/CarnetDeBord.jsx";
import { ToolsSidebar } from "./components/ToolsSidebar.jsx";
import { LayerFichePopup } from "./components/LayerFichePopup.jsx";
import { EscalePopupHost } from "./components/EscalePopup.jsx";
import { shouldCloseEscaleSheet } from "./components/escalePopup.js";
import NotForNavModal from "./components/NotForNavModal.jsx";
import { readNotForNavAccepted, writeNotForNavAccepted } from "./utils/notForNav.js";
import { SatelliteMetPanel } from "./components/SatelliteMetPanel.jsx";
import { useLang } from "./i18n/LangContext.jsx";
import { ITINERARY_POINTS } from "./constants/itineraryPoints";
import { SimulationFilmBar } from "./components/SimulationFilmBar.jsx";
import { DemoWalkthrough } from "./components/DemoWalkthrough.jsx";
import { TOUR_EDITED_WAIT_MS, tourEditedStep, wantsTourFromUrl } from "./components/demoWalkthrough.js";
import { RecomputeDialog } from "./components/RecomputeDialog.jsx";
import { useRouteWindProfile } from "./hooks/useRouteWindProfile.js";
import { useExpeditionSpeed } from "./hooks/useExpeditionSpeed.js";
import { useVoyageClock } from "./hooks/useVoyageClock.js";
import { useVirtualVessel } from "./hooks/useVirtualVessel.js";
import { useOfficialExpedition } from "./hooks/useOfficialExpedition.js";
import { useOfficialJournal } from "./hooks/useOfficialJournal.js";
import { legAtClockNow } from "./hooks/useLegContext.js";
import { useIciDossier } from "./hooks/useIciDossier.js";
import { useFilmZee } from "./hooks/useFilmZee.js";
import { useIciAlong } from "./hooks/useIciAlong.js";
import { useMomentCards } from "./hooks/useMomentCards.js";
import { useMoment } from "./hooks/useMoment.js";
import { useMomentJournal } from "./hooks/useMomentJournal.js";
import { useEscaleSheetState } from "./hooks/useEscaleSheetState.js";
import { useLogbookChat } from "./hooks/useLogbookChat.js";
import { filmSourceKey, followClockLineFromT0, useReplay, visibleFilmSubtitle } from "./hooks/useReplay.js";
import { useReplayVoice } from "./hooks/useReplayVoice.js";
import { dayMonth, expeditionStory } from "./engine/expeditionStory.js";
import { sumRainHours } from "./engine/eventRules.js";
import { layerForEntity } from "./engine/briefingLinks.js";
import { useSkipperOrders } from "./hooks/useSkipperOrders.js";
import { filmEventMarks } from "./engine/iciAlong.js";
import { kickLayerWarm, createDraftWarmer } from "./engine/layerWarm.js";
import { useAtlasLookup } from "./hooks/useAtlasLookup.js";
import { recetteMapView, recetteMonth } from "./utils/recetteQuery.js";
import {
  flattenRoute,
  interpolateAtNm,
  nearestNm,
  mapEscalesOnRoute,
  nextEscaleNm,
  prevEscaleNm,
  canNextEscale,
  canPrevEscale,
  filmLegContext,
  chapterAtNm,
  playheadOnPlay,
} from "./engine/routePlayhead.js";
import { detectAirEpisodes, mergeEpisodeMarks, sailNmToFilmNm } from "./engine/filmCast.js";
import { expeditionBoatKnots } from "./engine/playSpeeds.js";
import {
  DEFAULT_START_AT,
  DEFAULT_T0_ISO,
  etaHoursToFilmNm,
  formatMonthName,
  lookupVoyageClock,
  monthOfT0,
  sampleClockAtTime,
} from "./engine/voyageClock.js";
import { SERVER_MODE_TRACER, VIEW_SUIVRE, VIEW_TRACER } from "./constants/viewMode.js";
import { legsFromClockMarks } from "./components/iciMaintenant.js";
import { isRouteReady } from "./utils/routeReady.js";
import { resolveRouteSource, routeForSource } from "./utils/routeSource.js";
import {
  isSceneReady,
  playheadAligned,
  sceneMaskKey,
  shouldFocusTracerJump,
  shouldKeepSceneVisible,
} from "./utils/sceneGate.js";
import { routeStats, featuresToSegments, legsDistanceNm } from "./utils/geo.js";
import { highSeasRuledOut, nearestStopNm, replayHereFrame } from "./engine/iciBriefing.js";
import { waypointsFromCollection } from "./utils/waypointsFromCollection.js";
import { buildLocalCustomBriefing } from "./utils/customRouteBriefing.js";
import { normalizeExpeditionPlan } from "./utils/expeditionPlan.js";
import {
  activeRouteSegments,
  activeRouteStops,
} from "./utils/activeRoute.js";
import {
  SEGMENT_BATCH_SIZE,
  buildBerryLegs,
  coordsFromRoutePayload,
  isAirLegNames,
  isLandLegNames,
  isNonMaritimeLeg,
  orientCoords,
} from "./utils/berryLegs.js";
import { loadOfficialBerryRoute } from "./utils/routeFromOfficial.js";
import { isCinemaKey, restoreShowLayers, snapshotShowLayers } from "./utils/cinemaHotkey.js";
import { weatherLine as buildWeatherLine } from "./utils/weatherLine.js";
import { mapInsetVars, measureFilmBarOccupiedPx } from "./utils/filmBarLayout.js";
import { productHasData } from "./hooks/weatherSnapshot.js";
import { useSatellitePopup } from "./hooks/useSatellitePopup.js";
import { DRAW_MAX_POINTS, canFinishDrawnRoute, useRouteDrawing } from "./hooks/useRouteDrawing.js";
import { parseRouteFile } from "./utils/routeImport.js";
import { viewExportMode } from "./utils/routeExport.js";
import { attachClockIso, legendNowAndLive, officialNowMs, usePlanReview } from "./hooks/usePlanReview.js";
import { MapScene } from "./map/MapScene.jsx";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL;
const PLAN_CACHE_TTL = 24 * 60 * 60 * 1000;
const NOOP = () => {};
const EMPTY_MARITIME_LAYERS = Object.freeze({
  showGrib: false, setShowGrib: NOOP, loadingGrib: false, errorGrib: null,
  showZee: false, setShowZee: NOOP, loadingZee: false, errorZee: null,
  showPorts: false, setShowPorts: NOOP, loadingPorts: false, errorPorts: null,
  showBalisage: false, setShowBalisage: NOOP, loadingBalisage: false, errorBalisage: null,
  showBiProjects: false, setShowBiProjects: NOOP, loadingBiProjects: false, errorBiProjects: null,
  showBiMarinas: false, setShowBiMarinas: NOOP, loadingBiMarinas: false, errorBiMarinas: null,
  showBiCapitaineries: false, setShowBiCapitaineries: NOOP, loadingBiCapitaineries: false, errorBiCapitaineries: null,
  showBiPoe: false, setShowBiPoe: NOOP, loadingBiPoe: false, errorBiPoe: null,
  showBiAmp: false, setShowBiAmp: NOOP, loadingBiAmp: false, errorBiAmp: null,
  showSextant: false, setShowSextant: NOOP, showArgo: false, setShowArgo: NOOP,
  showOdatis: false, setShowOdatis: NOOP, showEdmed: false, setShowEdmed: NOOP,
  showCsr: false, setShowCsr: NOOP, loadingScienceCatalog: false, errorScienceCatalog: null,
  showBathymetry: false, setShowBathymetry: NOOP, loadingBathymetry: false, errorBathymetry: null,
  showFonds: false, setShowFonds: NOOP, loadingFonds: false, errorFonds: null,
  showCables: false, setShowCables: NOOP, loadingCables: false, errorCables: null,
  showClimoWind: false, setShowClimoWind: NOOP, showClimoWave: false, setShowClimoWave: NOOP,
  showClimoCurrent: false, setShowClimoCurrent: NOOP, showClimoCyclones: false, setShowClimoCyclones: NOOP,
});

function PanelCrashProbe({ panel }) {
  if ((import.meta.env.DEV || import.meta.env.VITE_NAVIGUIDE_CRASHTEST === "1") && new URLSearchParams(window.location.search).get("crashtest") === "panel" && panel === "sidebar") {
    throw new Error("NAVIGUIDE panel crash test");
  }
  return null;
}

function planCacheKey(lang) { return `naviguide_sim_plan_v1_${lang}`; }
function getCachedPlan(lang) {
  try {
    const raw = localStorage.getItem(planCacheKey(lang));
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts > PLAN_CACHE_TTL) { localStorage.removeItem(planCacheKey(lang)); return null; }
    return normalizeExpeditionPlan(data);
  } catch { return null; }
}
function setCachedPlan(lang, data) {
  const plan = normalizeExpeditionPlan(data);
  if (!plan) return;
  try { localStorage.setItem(planCacheKey(lang), JSON.stringify({ data: plan, ts: Date.now() })); } catch { /* quota */ }
}

export default function App() {
  const { lang, t } = useLang();
  const sceneApiRef = useRef(null);
  const [sceneApi, setSceneApi] = useState(null);
  const [playback, setPlayback] = useState({
    nm: 0,
    playing: false,
    profile: "normal",
    jumpToken: 0,
    holdingStation: null,
    holding: false,
    totalNm: 0,
    sailTotalNm: 0,
  });
  const [maritimeLayerState, setMaritimeLayerState] = useState(null);
  const maritimeLayers = maritimeLayerState || EMPTY_MARITIME_LAYERS;
  const [climoLayer, setClimoLayer] = useState({ loading: false, error: null, counts: null, source: null });
  const [isLightMode, setIsLightMode] = useState(false);

  const [segments, setSegments] = useState([]);
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [segProgress, setSegProgress] = useState({ done: 0, total: 0 });
  const [officialFallback, setOfficialFallback] = useState(false);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [expeditionPlan, setExpeditionPlan] = useState(null);
  const [polarData, setPolarData] = useState(null);
  const [briefingLoading, setBriefingLoading] = useState(false);

  const [view, setView] = useState(VIEW_SUIVRE);
  const [replayT0, setReplayT0] = useState(DEFAULT_T0_ISO);
  const [cinemaMode, setCinemaMode] = useState(true);
  const [filmFullscreen, setFilmFullscreen] = useState(false);
  const filmLayerSnapRef = useRef(null);
  const demoReplayStartedRef = useRef(false);
  // Visite, étape film : « Lire le film Rédigé » attend que le plan rédigé soit chargé.
  const [demoEditedPending, setDemoEditedPending] = useState(false);
  const [demoEditedFellBack, setDemoEditedFellBack] = useState(false);
  // Lien profond `?tour=1` (README, Devpost) : la visite guidée s'ouvre au chargement.
  const [tourFromUrl] = useState(() => typeof window !== "undefined" && wantsTourFromUrl(window.location.search));
  const [hideFilmBar, setHideFilmBar] = useState(false);
  const [filmBarNode, setFilmBarNode] = useState(null);
  const [filmBarMeasuredPx, setFilmBarMeasuredPx] = useState(null);
  const filmBarRef = useCallback((node) => {
    setFilmBarNode(node);
  }, []);
  const [stopAuto, setStopAuto] = useState(false);
  const [escaleClear, setEscaleClear] = useState(0);
  // The skipper moved the clock (scrub, play, previous / next, journal):
  // a sheet opened from a flag then only stays near its own stop.
  const [clockMoveToken, setClockMoveToken] = useState(0);
  const noteClockMove = useCallback(() => setClockMoveToken((n) => n + 1), []);
  const [cameraFollow, setCameraFollow] = useState(false);
  const [cinemaRecapture, setCinemaRecapture] = useState(0);
  const [cameraFocusToken, setCameraFocusToken] = useState(0);
  const [userPreview, setUserPreview] = useState(false);
  const [skipperClickId, setSkipperClickId] = useState(null);
  const isSuivre = view === VIEW_SUIVRE;
  const isTracer = view === VIEW_TRACER;
  const [voyageFlat, setVoyageFlat] = useState(null);
  const [cameraPlaced, setCameraPlaced] = useState(false);
  const [sceneRevealed, setSceneRevealed] = useState(false);
  const [liveKnots, setLiveKnots] = useState(null);
  const cinemaSavedRef = useRef({ sidebar: true, tools: true });
  const drawRestoreRef = useRef({ view: VIEW_SUIVRE, center: null, zoom: null });
  const [customRoute, setCustomRoute] = useState(null);
  const [routeKind, setRouteKind] = useState("berry");
  const routeKindRef = useRef("berry");
  const berryFetchIdRef = useRef(0);
  const customFetchIdRef = useRef(0);
  const drawingModeRef = useRef(false);
  const customRouteRef = useRef(null);
  const armDrawingWorldRef = useRef(() => {});

  // The drawn route: points, searoute segments, undo / redo (hooks/useRouteDrawing.js).
  const drawingState = useRouteDrawing();
  const {
    drawingMode, setDrawingMode, drawnPoints, drawnSegments, drawingLoading, drawingNotice, canRedo,
    reset: _resetDrawState, addPoint: handleDrawingClick, undo: handleDrawUndo, redo: handleDrawRedo,
    importPoints: handleImportPoints,
    toGeoJson,
  } = drawingState;
  drawingModeRef.current = drawingMode;
  customRouteRef.current = customRoute;
  const draftWarmerRef = useRef(null);
  if (draftWarmerRef.current == null) draftWarmerRef.current = createDraftWarmer();
  const resetDrawState = useCallback(() => {
    draftWarmerRef.current.cancel();
    _resetDrawState();
  }, [_resetDrawState]);

  const [layerPopup, setLayerPopup] = useState(null);
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [clipboardToast, setClipboardToast] = useState(null);
  const [drawNotice, setDrawNotice] = useState(null);
  // Satellite / weather popup of a route click (hooks/useSatellitePopup.js).
  const satellite = useSatellitePopup();
  const {
    selected: selectedSatellite, setSelected: setSelectedSatellite, loading: satelliteLoading,
    tab: satelliteTab, setTab: setSatelliteTab, open: fetchSatellite, close: closeSatellite,
  } = satellite;
  const [pointInfoName, setPointInfoName] = useState("");
  const [pointInfoFlags, setPointInfoFlags] = useState([null, null]);

  const onFeature = useCallback((fiche) => {
    closeSatellite();
    setLayerPopup(fiche);
  }, [closeSatellite]);
  const handleSceneReady = useCallback((api) => {
    sceneApiRef.current = api;
    setSceneApi(api);
  }, []);
  const handleScenePlayback = useCallback((snapshot) => {
    setPlayback(snapshot);
  }, []);
  const handleLayerState = useCallback((layers) => {
    setMaritimeLayerState(layers);
  }, []);
  const handleClimatologyState = useCallback((state) => {
    setClimoLayer((previous) => (
      previous.loading === state.loading
      && previous.error === state.error
      && previous.counts === state.counts
        ? previous
        : state
    ));
  }, []);
  const handleCoordinatesCopied = useCallback((text) => {
    navigator.clipboard.writeText(text).then(() => {
      setClipboardToast(text);
      setTimeout(() => setClipboardToast(null), 2000);
    });
  }, []);
  const handleDrawingWaypointClick = useCallback((point, index) => {
    setPointInfoName(point?.name || "");
    setPointInfoFlags(point?.flags || []);
    setSelectedSatellite({
      lat: point?.lat,
      lon: point?.lon,
      drawPointIndex: index,
    });
  }, []);
  const carnetOpen = useCarnetPage();
  const [notForNavOk, setNotForNavOk] = useState(() => readNotForNavAccepted());
  const [notForNavOpen, setNotForNavOpen] = useState(false);
  const pendingLayerRef = useRef(null);
  const gateRef = useRef({
    allowed: notForNavOk,
    onNeed: (kind) => {
      pendingLayerRef.current = kind;
      setNotForNavOpen(true);
    },
  });
  gateRef.current.allowed = notForNavOk;

  // La source de route (Berry | ma route) est indépendante du mode :
  // Suivre peut suivre la route perso, Tracer peut montrer la Berry.
  const routeSource = resolveRouteSource(routeKind, customRoute);
  const suivreBerry = isSuivre && routeSource === "berry";
  const suivreCustom = isSuivre && routeSource === "custom";
  const playControlsActive = isTracer || suivreCustom;
  const routeForView = routeForSource(routeSource, customRoute);
  const routeReady = isRouteReady(segProgress) || (officialFallback && segments.length > 0);
  const activeStops = useMemo(() => activeRouteStops(routeForView, points.length ? points : ITINERARY_POINTS), [routeForView, points]);
  const activeSegments = useMemo(() => activeRouteSegments(routeForView, segments), [routeForView, segments]);
  const baseFlat = useMemo(() => flattenRoute(activeSegments), [activeSegments]);
  const flatRoute = voyageFlat || baseFlat;
  const escaleMarks = useMemo(
    () => mergeEpisodeMarks(mapEscalesOnRoute(activeStops, flatRoute), flatRoute, activeStops),
    [activeStops, flatRoute],
  );
  const cruiseKnots = useMemo(() => expeditionBoatKnots(polarData), [polarData]);
  const atlasWindRef = useRef(null);
  const [atlasRev, setAtlasRev] = useState(0);
  const atlasWindAt = useCallback((lat, lon, month) => {
    if (typeof atlasWindRef.current === "function") {
      return atlasWindRef.current(lat, lon, month);
    }
    return null;
  }, []);
  const voyage = useVoyageClock({
    flat: flatRoute,
    marks: escaleMarks,
    polarRaw: polarData?.raw || null,
    enabled: Boolean(flatRoute.points?.length) && routeReady,
    stops: activeStops,
    windAt: atlasWindAt,
    atlasRev,
    mode: suivreBerry ? "suivre" : SERVER_MODE_TRACER,
  });
  // L'horloge officielle ne sert que Suivre × Berry : jamais un
  // PUT /voyage/official avec les points d'une route perso.
  const official = useOfficialExpedition({
    enabled: suivreBerry,
    points: routeReady ? flatRoute.points : undefined,
    marks: routeReady ? escaleMarks : [],
    expeditionId: polarData?.expedition_id,
    clock: voyage.clock,
  });
  // Mémoire du voyage officiel (journal serveur) — lecture seule, Suivre × Berry.
  const officialJournal = useOfficialJournal({ enabled: suivreBerry });
  // Suivre × ma route : le même voyage serveur que Tracer (POST /voyage,
  // t0 = date de départ choisie, défaut aujourd'hui 08:00 UTC) donne l'horloge.
  const vessel = useVirtualVessel({
    enabled: (isTracer || suivreCustom) && routeReady,
    forecast: false,
    follow: suivreCustom,
    t0: voyage.t0,
    startAt: voyage.startAt,
    expeditionId: polarData?.expedition_id,
    routeKind,
    points: flatRoute.points,
    marks: escaleMarks,
  });
  const officialClock = suivreBerry ? (official.clock || voyage.clock) : voyage.clock;
  const officialEtaReady = Boolean(suivreBerry && official.clock);
  const officialLiveNowMs = suivreBerry ? officialNowMs(official.clock, official.live) : NaN;
  // Le film n'utilise pas le repli voyage.clock (script Simulation).
  const filmClock = suivreBerry ? official.clock : voyage.clock;
  const boatKnots = liveKnots > 0 ? liveKnots : cruiseKnots;

  // « Revoir l'expédition »: while it runs, the boat of the replay
  // stands in for the live one — the scene, the clock line, the story and
  // the cards all read `live`. Suivre only; Stop or the end hands back.
  const customVoyageId = suivreCustom ? (vessel.voyage?.voyageId || "") : "";
  const replay = useReplay({
    clock: filmClock,
    fallbackClock: voyage.clock,
    requireOfficialFilm: isSuivre,
    journal: suivreBerry ? officialJournal.journal : null,
    enabled: isSuivre && (suivreBerry || Boolean(customVoyageId)),
    voyageId: suivreCustom ? customVoyageId : "official",
    lang,
    marks: escaleMarks,
    destination: suivreBerry ? official.live : vessel.live,
    t0: suivreBerry ? replayT0 : (voyage.t0 || DEFAULT_T0_ISO),
  });
  // En Suivre, la position vit sur la source : horloge officielle pour
  // Berry, voyage serveur de ma route pour la perso. Tant que le serveur n'a
  // pas répondu, la position « à maintenant » se lit sur l'horloge client
  // (mêmes calculs : polaire + climatologie) — jamais une position inventée.
  const customClientLive = useMemo(() => {
    if (!suivreCustom || !voyage.clock) return null;
    return sampleClockAtTime(voyage.clock, new Date());
  }, [suivreCustom, voyage.clock]);
  const sourceLive = suivreCustom ? (vessel.live || customClientLive) : official.live;
  const live = isSuivre ? (replay.active && replay.live ? replay.live : sourceLive) : vessel.live;
  const previewing = Boolean(isSuivre && live && userPreview);
  const playheadReady = playheadAligned({
    isSuivre,
    previewing,
    playbackNm: playback.nm,
    liveFilmNm: live?.filmNm,
  });
  const hasRoute = Boolean(flatRoute.points?.length);
  const gateReady = isSceneReady({
    routeReady,
    hasRoute,
    cameraPlaced,
    playheadReady,
    isSuivre,
    hasLive: Boolean(live),
    previewing,
  });
  // RF7 / D1' : la vue monde se montre dès que la route et la caméra sont
  // posées — pas d'attente du live ni du playhead (aucun recadrage serveur).
  const worldReady = Boolean(routeReady && hasRoute && cameraPlaced);
  const sceneReady = gateReady || worldReady || shouldKeepSceneVisible({
    revealed: sceneRevealed,
    routeReady,
    hasRoute,
  });
  const clockSample = useMemo(() => {
    if (isSuivre && live && !previewing) return live;
    // Next / seek saute le dwell : un playhead posé sur une escale à hold
    // est quand même à quai (sinon la barre garde les kn de jambe).
    const x = Number(playback.nm) || 0;
    const onHold = (officialClock?.marks || []).some((m) => (
      (m.holdHours || 0) > 0 && Math.abs((m.filmNm ?? m.nm) - x) <= 0.45
    ));
    return lookupVoyageClock(officialClock, playback.nm, {
      atQuay: Boolean(playback.holding || onHold),
    });
  }, [isSuivre, live, previewing, officialClock, playback.nm, playback.holding]);
  const windProfile = useRouteWindProfile({
    flat: flatRoute,
    marks: escaleMarks,
    polarData,
    cruiseKnots,
    enabled: Boolean(officialClock),
    clock: officialClock,
  });

  const cast = playback.cast;
  const sample = useMemo(() => {
    if (!cast) return interpolateAtNm(flatRoute, playback.nm);
    const actor = cast.vehicle === "side" ? cast.side : cast.main;
    return {
      lat: actor.lat,
      lon: actor.lon,
      bearing: actor.bearing,
      nm: cast.sailNm,
    };
  }, [cast, flatRoute, playback.nm]);

  // Skipper orders: one character, boat read from the polar, saved in this tab.
  // Cinema keeps them active. The planning speed reads the polar at the wind
  // of the moment: GRIB at the boat in Suivre, climatology of the clock in Simulation.
  const skipperWind = suivreBerry
    ? (live?.kind === "forecast" && Number.isFinite(live.windKnots)
      ? { tws: live.windKnots, twd: live.dirFromDeg, heading: live.bearing ?? sample?.bearing, kind: "grib" }
      : null)
    : (Number.isFinite(clockSample?.windKnots)
      ? { tws: clockSample.windKnots, twd: clockSample.dirFromDeg, heading: sample?.bearing ?? clockSample.bearing, kind: "climatology" }
      : null);
  const skipper = useSkipperOrders({
    polar: polarData,
    mode: suivreBerry ? "suivre" : SERVER_MODE_TRACER,
    lang,
    wind: skipperWind,
  });

  const destMark = useMemo(
    () => chapterAtNm(escaleMarks, cast?.sailNm ?? playback.nm)?.to,
    [escaleMarks, cast?.sailNm, playback.nm],
  );
  const climoMonth = recetteMonth() || clockSample?.month || monthOfT0(voyage.t0, 0);
  const atlas = useAtlasLookup({
    enabled: routeReady,
    t0: voyage.t0,
    points: flatRoute.points,
    boatLat: replay.active && Number.isFinite(Number(official.live?.lat)) ? official.live.lat : sample?.lat,
    boatLon: replay.active && Number.isFinite(Number(official.live?.lon)) ? official.live.lon : sample?.lon,
    destLat: destMark?.lat,
    destLon: destMark?.lon,
    month: climoMonth,
  });
  useEffect(() => {
    atlasWindRef.current = atlas.windAt;
    if (atlas.revision !== atlasRev) setAtlasRev(atlas.revision);
  }, [atlas.windAt, atlas.revision, atlasRev]);

  const climoAnyOn = Boolean(
    maritimeLayers.showClimoWind
    || maritimeLayers.showClimoWave
    || maritimeLayers.showClimoCurrent
    || maritimeLayers.showClimoCyclones,
  );
  const climoMapsLabel = [
    maritimeLayers.showClimoWind && t("layerClimoWind"),
    maritimeLayers.showClimoWave && t("layerClimoWave"),
    maritimeLayers.showClimoCurrent && t("layerClimoCurrent"),
    maritimeLayers.showClimoCyclones && t("layerClimoCyclones"),
  ].filter(Boolean).join(" · ");

  const expeditionSpeed = useExpeditionSpeed({
    polarData,
    sample: cast?.vehicle === "plane" ? cast.main : sample,
    profile: playback.profile,
    playing: playback.playing && cast?.vehicle !== "plane",
    onLiveKnots: setLiveKnots,
    windSeries: windProfile.series,
    filmNm: playback.nm,
    clockSample,
    follow: isSuivre,
  });
  // Playback cast stays on the opening leg for the whole film (the scene
  // clock is paused). The step the bar and the Here sheet show is the
  // chapter at the replayed boat, not that frozen cast.
  const replayBoatNm = replay.active && replay.live
    ? Number(replay.live.sailNm ?? replay.live.filmNm)
    : NaN;
  const legContext = useMemo(() => {
    const onFilm = Number.isFinite(replayBoatNm);
    if (!cast && !onFilm) return null;
    return filmLegContext({
      marks: escaleMarks,
      nm: onFilm ? replayBoatNm : cast.sailNm,
      sample: onFilm ? replay.live : sample,
      totalNm: playback.sailTotalNm || flatRoute.totalNm,
      boatKnots: expeditionSpeed.knots,
      cast: onFilm ? null : cast,
    });
  }, [cast, sample, escaleMarks, playback.sailTotalNm, flatRoute.totalNm, expeditionSpeed.knots, replayBoatNm, replay.live]);

  const clockEtaHours = useMemo(() => {
    if (!officialClock || !legContext || legContext.finished || (legContext.nmRemainingToStop ?? 0) < 0.5) {
      return 0;
    }
    const destNm = legContext.chapter?.to?.filmNm ?? legContext.chapter?.to?.nm;
    if (destNm == null) return legContext.etaHours;
    return etaHoursToFilmNm(officialClock, playback.nm, destNm, { atQuay: playback.holding })
      ?? legContext.etaHours;
  }, [officialClock, legContext, playback.nm, playback.holding]);

  const hudLeg = useMemo(() => {
    if (!legContext) return null;
    const local = Number(clockSample?.speedKnots);
    const sailing = clockSample
      && (clockSample.vehicle === "main" || clockSample.vehicle === "side")
      && Number.isFinite(local);
    return {
      ...legContext,
      etaHours: officialClock ? clockEtaHours : legContext.etaHours,
      speedKnots: sailing ? Math.round(local * 10) / 10 : (officialClock ? null : legContext.speedKnots),
        kind: clockSample?.kind === "forecast"
          ? "forecast"
          : (suivreBerry ? "absent" : (clockSample?.kind || (officialClock ? "climatology" : legContext.kind))),
    };
  }, [legContext, clockSample, officialClock, clockEtaHours, suivreBerry]);

  const jambe = useMemo(() => {
    if (!hudLeg) return null;
    return {
      fromStop: hudLeg.fromStop,
      toStop: hudLeg.toStop,
      speedKnots: hudLeg.speedKnots,
      etaHours: hudLeg.etaHours,
      remainingNm: hudLeg.nmRemainingToStop ?? hudLeg.remainingNm,
      phase: hudLeg.phase,
      vehicle: hudLeg.vehicle,
    };
  }, [hudLeg]);

  const legendMarks = useMemo(() => (
    attachClockIso(
      escaleMarks,
      // Suivre × Berry : horloge officielle ; sans API, horloge locale
      //. Tracer : horloge du tracé seulement — pas official.live.
      (suivreBerry ? official.clock?.marks : null) || voyage.clock?.marks || [],
    )
  ), [escaleMarks, suivreBerry, official.clock, voyage.clock]);
  const { nowMs: clockNowMs, liveFilmNm: legendLiveFilmNm } = legendNowAndLive({
    suivreBerry,
    officialNowMs: officialLiveNowMs,
    officialLiveNm: official.live?.filmNm,
    sampleIso: clockSample?.iso,
    sampleFilmNm: clockSample?.filmNm,
    playbackNm: playback.nm,
  });

  const monthLabel = clockSample?.month
    ? formatMonthName(clockSample.month, lang)
    : "";
  // « Climatologie de septembre » n'est plus écrit sous l'étape : la date de
  // départ le dit déjà (revue du 19 sept.). Le mois reste sur le bandeau climato.
  const weatherLine = buildWeatherLine({
    isSuivre,
    gribReady: official.gribStatus === "ready",
  });
  const quayDays = clockSample?.holdHours > 0
    ? Math.round(clockSample.holdHours / 24)
    : 0;
  const atQuay = Boolean(clockSample?.atQuay);

  // Fiche d'escale (popup sur le drapeau, plus dans le panneau).
  const escale = useEscaleSheetState({
    lang, isSuivre, atQuay, clockSample, marks: legendMarks,
    filmActive: replay.active,
    clearToken: escaleClear,
    clockMoveToken,
  });
  const { stop: escaleStop, setStop: setEscaleStop, sheet: escaleSheet, open: openEscaleSheet, close: closeEscaleSheet } = escale;

  const nowLeg = useMemo(() => {
    if (!suivreBerry || !officialClock) return null;
    return legAtClockNow({
      clock: officialClock,
      now: sourceLive?.iso || Date.now(),
      marks: escaleMarks,
      cursor: playback.nm,
      t0: officialClock.t0,
      speedKnots: sourceLive?.speedKnots,
    });
  }, [suivreBerry, officialClock, sourceLive?.iso, sourceLive?.speedKnots, escaleMarks, playback.nm]);

  // Chatbot journal de bord: the client adds what only it knows —
  // the view, the film boat in Simulation, the polar, the skipper's orders.
  // Une seule vitesse — horloge en Suivre, prévue en Simulation.
  // Suivre reads the clock "now", not the playback cursor (a journal seek).
  const followNow = isSuivre && sourceLive && Number.isFinite(Number(sourceLive.lat))
    ? { lat: Number(sourceLive.lat), lon: Number(sourceLive.lon), iso: sourceLive.iso || null }
    : null;
  const chatBoatPos = isSuivre
    ? (followNow || (clockSample && Number.isFinite(clockSample.lat)
      ? { lat: clockSample.lat, lon: clockSample.lon, iso: clockSample.iso || null }
      : null))
    : (sample && Number.isFinite(sample.lat)
      ? { lat: sample.lat, lon: sample.lon, iso: clockSample?.iso || null }
      : null);
  const drawTip = drawingMode && drawnPoints.length ? drawnPoints[drawnPoints.length - 1] : null;
  const momentLat = Number(drawTip?.lat ?? chatBoatPos?.lat);
  const momentLon = Number(drawTip?.lon ?? chatBoatPos?.lon);
  const momentIso = drawTip
    ? null
    : (isSuivre
      ? (followNow?.iso || chatBoatPos?.iso || null)
      : (chatBoatPos?.iso || clockSample?.iso || null));
  const iciMoment = useMoment({
    lat: Number.isFinite(momentLat) ? Math.round(momentLat * 1000) / 1000 : null,
    lon: Number.isFinite(momentLon) ? Math.round(momentLon * 1000) / 1000 : null,
    t: momentIso ? String(momentIso).slice(0, 16) : undefined,
    mode: drawingMode && drawnPoints.length ? "drawn" : (isSuivre ? "follow" : SERVER_MODE_TRACER),
    lang,
    enabled: sceneReady,
    frozen: replay.active,
  });
  const momentMode = drawingMode && drawnPoints.length ? "drawn" : (isSuivre ? "follow" : SERVER_MODE_TRACER);
  // Suivre × ma route lit GET /voyage/{id}/moments (pas le stock Berry,
  // pas le journal local de Tracer). Sans voyageId : rien n'est servi comme prêt.
  const momentJournalMode = (suivreCustom && !customVoyageId)
    ? SERVER_MODE_TRACER
    : momentMode;
  const journalRouteId = momentJournalMode === "drawn"
    ? "drawn"
    : (momentJournalMode === "follow"
      ? (suivreCustom ? customVoyageId : "official")
      : (routeSource === "custom" ? "simulation:custom" : "simulation:official"));
  const momentJournal = useMomentJournal({
    mode: momentJournalMode,
    routeId: journalRouteId,
    incomingMoment: iciMoment.moment,
    until: momentIso,
    suivreCustom,
    lang,
    enabled: sceneReady && !(suivreCustom && !customVoyageId),
  });
  const displayKnots = isSuivre
    ? (atQuay ? 0 : (Number.isFinite(Number(clockSample?.speedKnots)) ? Number(clockSample.speedKnots) : null))
    : expeditionSpeed.knots;
  const displayRegime = clockSample?.regime || clockSample?.kind || null;
  const chatContextRef = useRef(null);
  chatContextRef.current = {
    view: isSuivre ? "suivre" : SERVER_MODE_TRACER,
    boat: chatBoatPos
      ? {
        ...chatBoatPos,
        speedKnots: Number.isFinite(displayKnots) ? displayKnots : null,
        atQuay,
        regime: displayRegime,
      }
      : null,
    polar: polarData ? { boat: polarData.boat_name || polarData.name || null, loaM: skipper.orders?.boat?.loaM, draftM: skipper.orders?.boat?.draftM, planningKn: skipper.orders?.values?.planningKn } : null,
    orders: !skipper.orders
      ? null
      : {
        profile: skipper.orders.profile,
        comfort: skipper.orders.comfort,
        knobs: skipper.orders.knobs,
        values: skipper.orders.values,
        expert: skipper.orders.expert,
        boat: skipper.orders.boat,
        budget: skipper.orders.budget,
      },
    leg: hudLeg ? { from: hudLeg.fromStop, to: hudLeg.toStop, remainingNm: hudLeg.remainingNm, etaHours: hudLeg.etaHours, speedKnots: hudLeg.speedKnots } : null,
  };
  const chatContextFn = useCallback(() => chatContextRef.current, []);
  const chat = useLogbookChat({ lang, contextFn: chatContextFn });

  const clockLine = officialClock?.vertices?.length && clockSample
    ? followClockLineFromT0({
      sailNm: isSuivre && !previewing
        ? (clockSample.sailNm ?? cast?.sailNm)
        : (cast?.sailNm ?? clockSample.sailNm),
      seaHours: clockSample.seaHours,
      iso: clockSample.iso,
      fromT0: officialClock.t0 || DEFAULT_T0_ISO,
      t0: suivreBerry ? replayT0 : (officialClock.t0 || DEFAULT_T0_ISO),
      lang,
    })
    : "";
  const sidebarPlaybackNm = isSuivre && live
    ? (Number(live.filmNm) || playback.nm)
    : playback.nm;
  const sidebarHudLeg = hudLeg;
  const sidebarClockSample = clockSample;
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    window.__naviguideDebug = {
      speed: Number.isFinite(displayKnots) ? displayKnots : null,
      regime: displayRegime,
      atQuay,
    };
    return () => {
      if (window.__naviguideDebug) delete window.__naviguideDebug;
    };
  }, [displayKnots, displayRegime, atQuay]);

  useEffect(() => {
    if (clockSample?.speedKnots > 0) setLiveKnots(clockSample.speedKnots);
  }, [clockSample?.speedKnots]);

  useEffect(() => {
    if (isSuivre) {
      setVoyageFlat(null);
      return;
    }
    if (vessel.voyage?.points?.length && vessel.voyage.routeRev > 0) {
      const pts = vessel.voyage.points;
      const last = pts[pts.length - 1];
      setVoyageFlat({
        points: pts,
        totalNm: last?.cumNm || 0,
        totalFilmNm: last?.filmCum || last?.cumNm || 0,
        episodes: detectAirEpisodes(pts),
      });
    }
  }, [isSuivre, vessel.voyage?.routeRev, vessel.voyage?.points]);

  const goLive = useCallback(() => {
    if (!live) return;
    setUserPreview(false);
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(Number(live.filmNm) || 0, { jump: true });
  }, [live, sceneApi]);

  useEffect(() => {
    if (isSuivre) setUserPreview(false);
  }, [isSuivre]);

  const livePrimedRef = useRef(false);
  useEffect(() => {
    if (!isSuivre) {
      livePrimedRef.current = false;
      return;
    }
    if (!routeReady || !live || userPreview) return;
    const target = Number(live.filmNm) || 0;
    // Replay: the boat moves ~200 nm per second of wall clock — jump
    // every frame rather than pile up eased seeks.
    if (Math.abs(playback.nm - target) > (live.replay ? 0.2 : 2)) {
      sceneApiRef.current?.playback.seek(target, { jump: Boolean(live.replay) });
    }
    livePrimedRef.current = true;
  }, [routeReady, isSuivre, live?.filmNm, live?.replay, userPreview, playback.nm, sceneApi]);

  useEffect(() => {
    if (gateReady || worldReady) setSceneRevealed(true);
  }, [gateReady, worldReady]);
  useEffect(() => {
    if (!routeReady) setSceneRevealed(false);
  }, [routeReady]);

  // Tracer keeps its playhead across a visit to Suivre: coming back
  // resumes where the film was, not at Saint-Maur (revue du 19 sept.).
  // Captured when leaving Tracer (selectView), read when coming back.
  const tracerNmRef = useRef(0);

  const tracerPrimedRef = useRef(false);
  useEffect(() => {
    if (!isTracer) {
      tracerPrimedRef.current = false;
      return;
    }
    if (!routeReady || tracerPrimedRef.current) return;
    tracerPrimedRef.current = true;
    voyage.setStartAt("saint-maur");
    voyage.resetToToday();
    sceneApiRef.current?.playback.setProfile("normal");
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(tracerNmRef.current || 0, { jump: true });
  }, [isTracer, routeReady, voyage.setStartAt, voyage.resetToToday, sceneApi]);

  // Playing the film follows the boat; a manual drag lets go (onManualNavigation).
  useEffect(() => {
    if (isTracer && playback.playing) setCameraFollow(true);
  }, [isTracer, playback.playing]);

  const canRecompute = Boolean(
    isTracer
    && cast?.vehicle === "main"
    && vessel.voyage?.voyageId,
  );

  const alongPack = useIciAlong({
    enabled: Boolean(cast && routeReady) && !replay.active && !drawingMode,
    flat: flatRoute,
    // When a route is drawn, sample that track — never GET /ici/pearls (Berry).
    customRoute: routeForView,
    fromNm: chapterAtNm(escaleMarks, cast?.sailNm ?? playback.nm)?.from?.nm,
    toNm: destMark?.nm,
    boatNm: cast?.sailNm ?? clockSample?.sailNm ?? playback.nm,
    boatLat: sample?.lat,
    boatLon: sample?.lon,
    mode: isSuivre ? "suivre" : SERVER_MODE_TRACER,
    month: climoMonth,
    orders: skipper.orders,
    // The Berry route has canonical pearls warmed on the server; a drawn route samples itself.
    canonical: routeSource === "berry",
  });

  const highSeasRuled = highSeasRuledOut({
    vehicle: clockSample?.vehicle || jambe?.vehicle || null,
    nearStopNm: nearestStopNm(clockSample?.lat, clockSample?.lon, legendMarks),
    fromStop: jambe?.fromStop,
    toStop: jambe?.toStop,
  });
  const momentHighSeasRuled = highSeasRuledOut({
    vehicle: drawTip ? null : (clockSample?.vehicle || jambe?.vehicle || null),
    nearStopNm: nearestStopNm(momentLat, momentLon, legendMarks),
    fromStop: jambe?.fromStop,
    toStop: jambe?.toStop,
  });
  const replayPos = replay.active && replay.live
    && Number.isFinite(Number(replay.live.lat)) && Number.isFinite(Number(replay.live.lon))
    ? replay.live
    : null;
  const filmZee = useFilmZee({
    enabled: Boolean(replayPos),
    lat: replayPos?.lat,
    lon: replayPos?.lon,
  });
  const replayFrame = useMemo(() => {
    if (!replayPos) return null;
    return replayHereFrame({
      lat: Number(replayPos.lat),
      lon: Number(replayPos.lon),
      marks: legendMarks,
      zee: filmZee,
      logLeg: hudLeg?.fromStop ? { from: hudLeg.fromStop, to: hudLeg.toStop } : null,
      lang,
    });
  }, [replayPos, legendMarks, filmZee, hudLeg?.fromStop, hudLeg?.toStop, lang]);
  const iciPos = replayPos || (suivreBerry ? sourceLive : null);
  const iciPack = useIciDossier({
    highSeasRuledOut: highSeasRuled,
    enabled: Boolean(cast),
    frozen: replay.active,
    replayText: replay.active ? (replayFrame?.statusText || "") : "",
    stories: !replay.active && replay.filmStyle === "written",
    cast,
    snappedPosition: legContext?.snappedPosition,
    at: Number.isFinite(Number(iciPos?.lat)) && Number.isFinite(Number(iciPos?.lon))
      ? { lat: Number(iciPos.lat), lon: Number(iciPos.lon) }
      : null,
    polarMeta: polarData,
    jambe,
    lang,
    month: climoMonth,
    destLat: destMark?.lat,
    destLon: destMark?.lon,
    climatology: atlas.boatPoint
      ? {
        kind: "climatology",
        source: "atlas",
        month: climoMonth,
        period: atlas.boatPoint.period,
        doi: atlas.boatPoint.doi,
        point: atlas.boatPoint,
        crossings: atlas.boatPoint.crossings || atlas.boatPoint.cyclone?.crossings_if_leg,
      }
      : null,
    mode: isSuivre ? "suivre" : SERVER_MODE_TRACER,
    cinema: cinemaMode,
    playbackProfile: playback.profile,
    cumNm: cast?.sailNm ?? clockSample?.sailNm ?? playback.nm,
    filmCum: isSuivre && live && !previewing ? (Number(live.filmNm) || playback.nm) : playback.nm,
    clockMin: Number.isFinite(clockSample?.seaHours) ? clockSample.seaHours * 60 : null,
    rainMm: suivreBerry ? official.live?.rainMm ?? null : null,
    rain3hMm: suivreBerry ? sumRainHours(official.grib?.samples, official.live?.iso, 3) : null,
    gribWindKnots: suivreBerry ? official.live?.windKnots ?? null : null,
    gribDirFromDeg: suivreBerry ? official.live?.dirFromDeg ?? null : null,
    gribHs: suivreBerry ? official.live?.hs ?? null : null,
    gribModel: suivreBerry ? official.live?.model ?? official.gribModel ?? null : null,
    gribStatus: suivreBerry ? official.gribStatus : null,
    along: alongPack.index,
    nearestBag: alongPack.nearestBag,
    skipperClickId,
    orders: skipper.orders,
  });

  // Carte du moment : NOW (sécurité / décision) + FREE (information), nourries
  // par le registre jugé et le sac. Jamais un appel réseau de son côté.
  const momentFilmCum = isSuivre && live && !previewing ? (Number(live.filmNm) || playback.nm) : playback.nm;
  const cardHud = suivreBerry && nowLeg?.fromStop ? nowLeg : hudLeg;
  const momentLegId = cardHud ? `${cardHud.fromStop || ""}→${cardHud.toStop || ""}` : null;
  // What the escale card says when the boat leaves a stopover.
  const momentLeg = useMemo(() => {
    if (!cardHud?.fromStop) return null;
    const from = legendMarks.find((m) => m.name === cardHud.fromStop);
    const to = cardHud.toStop ? legendMarks.find((m) => m.name === cardHud.toStop) : null;
    const land = isLandLegNames(cardHud.fromStop, cardHud.toStop) || cardHud.vehicle === "land";
    const sailNm = from && to ? Math.max(0, (Number(to.nm) || 0) - (Number(from.nm) || 0)) : null;
    const filmDelta = from && to
      ? Math.max(0, (Number(to.filmNm ?? to.nm) || 0) - (Number(from.filmNm ?? from.nm) || 0))
      : null;
    const fromMs = Date.parse(from?.iso ?? "");
    const toMs = Date.parse(to?.iso ?? "");
    const roadHours = Number.isFinite(fromMs) && Number.isFinite(toMs)
      ? Math.max(0, Math.round((toMs - fromMs) / 3_600_000))
      : null;
    return {
      fromStop: cardHud.fromStop,
      toStop: cardHud.toStop || null,
      holdDays: from?.holdHours > 0 ? Math.round(from.holdHours / 24) : 0,
      legNm: land ? (filmDelta || sailNm) : sailNm,
      kind: land ? "land" : undefined,
      roadHours: land ? roadHours : null,
      etaLabel: to?.iso ? dayMonth(to.iso, lang) : null,
      lat: from?.lat,
      lon: from?.lon,
    };
  }, [cardHud?.fromStop, cardHud?.toStop, cardHud?.vehicle, legendMarks, lang]);
  // Where the boat is on its leg: a port card only shows near that port.
  const momentLeftNm = Number(cardHud?.nmRemainingToStop ?? cardHud?.remainingNm);
  const momentLegNm = Number(momentLeg?.legNm);
  const momentProgress = useMemo(() => {
    if (!cardHud?.fromStop) return null;
    const leftNm = Number.isFinite(momentLeftNm) ? Math.round(momentLeftNm) : null;
    const doneNm = leftNm != null && Number.isFinite(momentLegNm) && momentLegNm > 0
      ? Math.max(0, Math.round(momentLegNm - leftNm))
      : null;
    return { fromStop: cardHud.fromStop, toStop: cardHud.toStop || null, leftNm, doneNm };
  }, [cardHud?.fromStop, cardHud?.toStop, momentLeftNm, momentLegNm]);
  const moments = useMomentCards({
    enabled: sceneReady && !drawingMode && !replay.active,
    events: iciPack.events,
    bag: iciPack.dossier,
    filmCum: momentFilmCum,
    playing: playback.playing,
    mode: isSuivre ? "suivre" : SERVER_MODE_TRACER,
    lang,
    written: !replay.active && replay.filmStyle === "written",
    legId: momentLegId,
    leg: momentLeg,
    officialMoments: suivreBerry ? momentJournal.entries : null,
    nowIso: suivreBerry ? (sourceLive?.iso || null) : null,
    boat: chatBoatPos,
    legProgress: momentProgress,
  });

  // Stop auto : le film s'arrête sur chaque nouvelle carte (NOW, et FREE hors
  // boucle) pour laisser le temps de lire ; Lecture repart.
  const lastCardKeysRef = useRef({ now: null, free: null });
  useEffect(() => {
    const nowKey = moments.now?.key || null;
    const freeKey = moments.free?.key || null;
    const prevKeys = lastCardKeysRef.current;
    const newNow = Boolean(nowKey && nowKey !== prevKeys.now);
    const newFree = Boolean(freeKey && freeKey !== prevKeys.free && !moments.free?.loop);
    lastCardKeysRef.current = { now: nowKey, free: freeKey };
    if (!isTracer || !stopAuto || !playback.playing) return;
    if (newNow || newFree) sceneApiRef.current?.playback.pause();
  }, [moments.now?.key, moments.free?.key, moments.free?.loop, isTracer, stopAuto, playback.playing]);

  // Récit : film serveur (Berry = horloge officielle + journal ; ma route =
  // chapitres de GET /voyage/{id}/film). Jamais le brut local servi comme prêt.
  // Revoir place le bateau au jour 0. Le texte du panneau reste celui de
  // l'horloge officielle : le playhead ne doit pas effacer les escales déjà
  // franchies (RA2 lit ce texte pendant que le film joue).
  const storyLive = replay.active && sourceLive ? sourceLive : live;
  const storyLeg = replay.active ? null : (nowLeg || hudLeg);
  const storyParagraphs = useMemo(() => {
    if (suivreCustom) return replay.filmParagraphs || [];
    if (!suivreBerry || !officialClock) return [];
    const datedLegend = (legendMarks || []).some((m) => m?.iso);
    return expeditionStory({
      clock: officialClock,
      marks: datedLegend ? legendMarks : (officialClock.marks || legendMarks),
      live: storyLive,
      leg: storyLeg,
      journal: officialJournal.journal,
      now: storyLive?.iso || Date.now(),
      lang,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suivreCustom, suivreBerry, officialClock, legendMarks, storyLive?.iso, storyLive?.status, storyLive?.atQuay, storyLive?.windKnots, storyLive?.filmNm, storyLeg?.toStop, storyLeg?.fromStop, Math.round(storyLeg?.remainingNm || 0), officialJournal.journal, lang, replay.filmParagraphs]);
  // During a replay, Écouter / useReplayVoice read the current
  // paragraph; otherwise the story + briefing (Suivre) or the briefing alone.
  const speechText = replay.active
    ? (replay.chapterText || null)
    : isSuivre
      ? [...storyParagraphs, iciPack.briefing].filter(Boolean)
      : (iciPack.briefing || null);

  useReplayVoice({
    active: replay.active,
    voice: replay.voice,
    lang,
    chapterText: replay.chapterText,
    chapterIdx: replay.chapterIdx,
    rate: replay.voiceRate,
    onBoundary: replay.onVoiceBoundary,
    onEnd: replay.onVoiceEnd,
    onLeadFailed: replay.onVoiceLeadFailed,
    onSentenceStart: replay.onSentenceStart,
    onSentenceEnd: replay.onSentenceEnd,
    isVoiceHeld: replay.isVoiceHeld,
  });

  useEffect(() => {
    if (replay.active) closeEscaleSheet();
  }, [replay.active, closeEscaleSheet]);

  const recaptureRef = useRef(null);
  const openEscaleFromUi = useCallback((next) => {
    if (replay.active) return;
    openEscaleSheet(next);
  }, [replay.active, openEscaleSheet]);

  // Suivre × ma route : même barre que Berry ; Revoir actif quand
  // GET /voyage/{id}/film est ready, sinon grisé « en préparation ».
  const replayControls = useMemo(() => (isSuivre && officialClock ? {
    active: replay.active,
    canStart: replay.canStart,
    progress: replay.progress,
    voice: replay.voice,
    subtitle: visibleFilmSubtitle(replay.subtitle || replay.chapterText, {
      fromName: replay.fromName,
      toName: replay.toName,
    }),
    fromName: replay.fromName,
    toName: replay.toName,
    subtitlePlace: replay.subtitlePlace,
    targetSeconds: replay.targetSeconds,
    estimatedSeconds: replay.estimatedSeconds,
    variantEstimates: replay.variantEstimates,
    onDuration: replay.setTargetSeconds,
    onStart: () => {
      if (shouldCloseEscaleSheet({ replayStarting: true })) {
        closeEscaleSheet();
        setEscaleClear((n) => n + 1);
      }
      if (replay.start()) {
        filmLayerSnapRef.current = snapshotShowLayers(maritimeLayers);
        // The camera picks the replayed boat up and follows it (same as Cinema's recapture).
        recaptureRef.current?.();
        setSidebarOpen(true);
      }
    },
    onStop: () => {
      setFilmFullscreen(false);
      setCameraFollow(true);
      if (view !== VIEW_SUIVRE) setView(VIEW_SUIVRE);
      restoreShowLayers(maritimeLayers, filmLayerSnapRef.current);
      filmLayerSnapRef.current = null;
      replay.stop();
      if (shouldCloseEscaleSheet({ replayActive: true })) closeEscaleSheet();
    },
    onVoice: replay.setVoice,
    source: replay.filmSource,
    reviewedBy: replay.filmReviewedBy,
    model: replay.filmModel,
    webContext: replay.filmWebContext,
    receipt: replay.filmReceipt,
    writing: replay.filmWriting,
    style: replay.filmStyle,
    hasWritten: replay.hasWritten,
    writtenUnavailable: replay.writtenUnavailable,
    onStyle: replay.setFilmStyle,
    t0: suivreBerry ? replayT0 : voyage.t0,
    onT0: suivreBerry ? setReplayT0 : voyage.setT0,
    remoteStatus: replay.remoteStatus,
    onRetryLoad: replay.retryFilmLoad,
    customFilm: suivreCustom,
  } : null), [isSuivre, officialClock, suivreBerry, suivreCustom, view, closeEscaleSheet, maritimeLayers, replay.active, replay.canStart, replay.progress, replay.voice, replay.chapterText, replay.fromName, replay.toName, replay.subtitle, replay.subtitlePlace, replay.targetSeconds, replay.estimatedSeconds, replay.variantEstimates, replay.setTargetSeconds, replay.start, replay.stop, replay.setVoice, replay.filmSource, replay.filmReviewedBy, replay.filmModel, replay.filmWebContext, replay.filmReceipt, replay.filmWriting, replay.filmStyle, replay.hasWritten, replay.writtenUnavailable, replay.setFilmStyle, replay.remoteStatus, replay.retryFilmLoad, replayT0, voyage.t0, voyage.setT0]);

  const playheadNmRef = useRef(0);
  playheadNmRef.current = playback.nm;

  const handleSimNext = useCallback(() => {
    if (!playControlsActive) return;
    if (isSuivre) setUserPreview(true);
    const focusBoat = shouldFocusTracerJump({
      isTracer,
      playing: playback.playing,
    });
    noteClockMove();
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(nextEscaleNm(escaleMarks, playheadNmRef.current), { jump: true });
    if (focusBoat) setCameraFocusToken((token) => token + 1);
  }, [playback.playing, escaleMarks, isTracer, playControlsActive, isSuivre, sceneApi, noteClockMove]);

  const handleSimPrev = useCallback(() => {
    if (!playControlsActive) return;
    if (isSuivre) setUserPreview(true);
    const focusBoat = shouldFocusTracerJump({
      isTracer,
      playing: playback.playing,
    });
    const target = prevEscaleNm(escaleMarks, playheadNmRef.current);
    const origin = Number(escaleMarks?.[0]?.filmNm ?? escaleMarks?.[0]?.nm) || 0;
    if (isTracer && target <= origin + 1) voyage.resetToToday();
    noteClockMove();
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(target, { jump: true });
    if (focusBoat) setCameraFocusToken((token) => token + 1);
  }, [playback.playing, escaleMarks, isTracer, playControlsActive, isSuivre, sceneApi, voyage.resetToToday, noteClockMove]);

  const handleCatamaranDrag = useCallback((pos) => {
    noteClockMove();
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(sailNmToFilmNm(flatRoute, nearestNm(flatRoute, pos.lat, pos.lon)));
  }, [flatRoute, sceneApi, noteClockMove]);

  const recaptureBoat = useCallback(() => {
    setCameraFollow(true);
    setCinemaRecapture((n) => n + 1);
  }, []);
  recaptureRef.current = recaptureBoat;

  /** BI toggle setter for a briefing entity's layer (null when the layer has no toggle). */
  const LAYER_SETTER = {
    poe: "setShowBiPoe",
    amp: "setShowBiAmp",
    projects: "setShowBiProjects",
    marinas: "setShowBiMarinas",
    capitaineries: "setShowBiCapitaineries",
    wpi: "setShowPorts",
    aton: "setShowBalisage",
    sextant: "setShowSextant",
    csr: "setShowCsr",
    argo: "setShowArgo",
    odatis: "setShowOdatis",
    edmed: "setShowEdmed",
  };

  /**
   * Briefing link "voir sur la carte": switch the place's layer on, then pin
   * it and fit the map on the boat AND the place. Never a GET /ici, never a chat.
   */
  const handleBriefingFocus = useCallback((entity) => {
    if (!entity || !Number.isFinite(entity.lat) || !Number.isFinite(entity.lon)) return;
    const layer = layerForEntity(entity);
    const setter = layer ? maritimeLayers[LAYER_SETTER[layer]] : null;
    if (typeof setter === "function") setter(true);
    const at = iciPack.dossier?.at;
    const boat = at && Number.isFinite(at.lat) && Number.isFinite(at.lon) ? { lat: at.lat, lon: at.lon } : null;
    sceneApiRef.current?.briefing?.focus(entity, boat);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maritimeLayers, iciPack.dossier]);

  const leaveCinema = useCallback(() => {
    setSidebarOpen(cinemaSavedRef.current.sidebar);
    setToolsOpen(cinemaSavedRef.current.tools);
    setCinemaMode(false);
    setHideFilmBar(false);
    // The camera keeps following the boat: leaving Cinema is not a manual drag.
  }, []);

  const toggleCinema = useCallback(() => {
    if (!cinemaMode) {
      cinemaSavedRef.current = { sidebar: sidebarOpen, tools: toolsOpen };
      setSidebarOpen(false);
      setToolsOpen(false);
      setCinemaMode(true);
      recaptureBoat();
      return;
    }
    if (!cameraFollow) {
      recaptureBoat();
      return;
    }
    leaveCinema();
  }, [cinemaMode, cameraFollow, sidebarOpen, toolsOpen, recaptureBoat, leaveCinema]);

  // Met le dessin en cours de côté (sans Annuler, le brouillon reste).
  const parkDrawing = useCallback(() => {
    if (!drawingModeRef.current) return;
    setDrawingMode(false);
    closeSatellite();
    sceneApiRef.current?.endDrawingWorld?.();
  }, [closeSatellite]);

  const selectView = useCallback((next) => {
    if (shouldCloseEscaleSheet({ nextView: next, replayActive: replay.active })) {
      closeEscaleSheet();
      setEscaleClear((n) => n + 1);
    }
    if (next === VIEW_SUIVRE && replay.active) replay.stop();
    if (next === VIEW_SUIVRE && view === VIEW_TRACER) tracerNmRef.current = playheadNmRef.current;
    // Quitter Tracer pendant un dessin met le brouillon de côté, sans Annuler.
    if (next !== VIEW_TRACER) parkDrawing();
    setView(next);
    if (next === VIEW_SUIVRE) {
      // Suivre × ma route garde le départ du tracé (même voyage serveur
      // que Tracer) ; Suivre × Berry repart de La Rochelle, comme avant.
      voyage.setStartAt(routeKindRef.current === "custom" ? "saint-maur" : DEFAULT_START_AT);
      sceneApiRef.current?.playback.pause();
      setUserPreview(false);
      if (!cinemaMode) {
        cinemaSavedRef.current = { sidebar: sidebarOpen, tools: toolsOpen };
      }
      setSidebarOpen(false);
      setToolsOpen(false);
      setCinemaMode(true);
      recaptureBoat();
    } else {
      voyage.setStartAt("saint-maur");
      sceneApiRef.current?.playback.setProfile("normal");
      sceneApiRef.current?.playback.pause();
      sceneApiRef.current?.playback.seek(tracerNmRef.current || 0, { jump: true });
      if (view === VIEW_SUIVRE) {
        leaveCinema();
        setSidebarOpen(true);
        setToolsOpen(true);
      }
      // Entrée en Tracer = dessin ouvert (brouillon vide ou déjà là).
      // Une route perso terminée reste affichée ; Annuler est le seul abandon.
      if (!(routeKindRef.current === "custom" && customRouteRef.current)) {
        armDrawingWorldRef.current(VIEW_TRACER);
      }
    }
  }, [
    cinemaMode,
    closeEscaleSheet,
    closeSatellite,
    leaveCinema,
    parkDrawing,
    recaptureBoat,
    replay.active,
    replay.stop,
    sceneApi,
    sidebarOpen,
    toolsOpen,
    view,
    voyage.setStartAt,
  ]);


  useEffect(() => {
    if (isSuivre) voyage.setStartAt(routeSource === "custom" ? "saint-maur" : DEFAULT_START_AT);
  }, [isSuivre, routeSource, voyage.setStartAt]);

  useEffect(() => {
    if (!isSuivre) setFilmFullscreen(false);
  }, [isSuivre]);

  useEffect(() => {
    // Suivre × ma route garde une lecture jouable (Play / vitesses) ;
    // Suivre × Berry reste au temps réel (1 s = 1 s), comme avant.
    if (isSuivre) sceneApiRef.current?.playback.setProfile(suivreCustom ? "normal" : "real");
  }, [isSuivre, suivreCustom, sceneApi]);

  // A new route (drawn or Berry again) starts its film at 0 — a mode switch does not.
  useEffect(() => {
    if (!isTracer) return;
    tracerNmRef.current = 0;
    voyage.resetToToday();
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customRoute, sceneApi]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target?.closest?.("input, textarea, select, [contenteditable]")) return;
      if (e.target?.closest?.("button") && e.code === "Space") return;
      if (e.target?.closest?.("[role='slider']") && /^(Arrow|Home$|End$|Page)/.test(e.code)) return;
      if (isTracer && e.code === "Space") {
        e.preventDefault();
        sceneApiRef.current?.playback.toggle();
      } else if (isTracer && e.code === "ArrowRight") {
        e.preventDefault();
        handleSimNext();
      } else if (isTracer && e.code === "ArrowLeft") {
        e.preventDefault();
        handleSimPrev();
      } else if (isCinemaKey(e)) {
        e.preventDefault();
        toggleCinema();
      } else if (isSuivre && e.code === "KeyL") {
        e.preventDefault();
        goLive();
      } else if (e.code === "Escape" && filmFullscreen) {
        e.preventDefault();
        setFilmFullscreen(false);
      } else if (e.code === "Escape" && cinemaMode && !drawingMode) {
        e.preventDefault();
        leaveCinema();
      } else if (isTracer && e.code === "Digit1") {
        sceneApiRef.current?.playback.setProfile("real");
      } else if (isTracer && e.code === "Digit2") {
        sceneApiRef.current?.playback.setProfile("read");
      } else if (isTracer && e.code === "Digit3") {
        sceneApiRef.current?.playback.setProfile("normal");
      } else if (isTracer && e.code === "Digit4") {
        sceneApiRef.current?.playback.setProfile("fast");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cinemaMode, drawingMode, filmFullscreen, goLive, handleSimNext, handleSimPrev, isTracer, isSuivre, leaveCinema, sceneApi, toggleCinema]);

  // Capture : la bulle événement coupe Échap en phase bulle.
  useEffect(() => {
    if (!filmFullscreen) return undefined;
    const onEsc = (e) => {
      if (e.code !== "Escape" && e.key !== "Escape" && e.key !== "Esc") return;
      e.preventDefault();
      e.stopPropagation();
      setFilmFullscreen(false);
    };
    window.addEventListener("keydown", onEsc, true);
    return () => window.removeEventListener("keydown", onEsc, true);
  }, [filmFullscreen]);

  const applyBerryBriefing = useCallback(() => {
    setExpeditionPlan(getCachedPlan(lang) || normalizeExpeditionPlan({ executive_briefing: t("berryLocalBriefing") }));
    setBriefingLoading(false);
  }, [lang, t]);

  const handleRouteSwitchToBerry = useCallback(() => {
    // La pilule Berry affiche la vitrine, sans Annuler et sans jeter le brouillon.
    parkDrawing();
    customFetchIdRef.current += 1;
    routeKindRef.current = "berry";
    setCustomRoute(null);
    setRouteKind("berry");
    setVoyageFlat(null);
    // En Suivre, le bateau se recale sur le live de la nouvelle source.
    setUserPreview(false);
    sceneApiRef.current?.playback.pause();
    applyBerryBriefing();
  }, [applyBerryBriefing, parkDrawing]);

  // The guided demo changes only visible app state. It does not inject sample data
  // or reset a user-created route.
  const stopDemoOwnedReplay = useCallback(() => {
    if (!demoReplayStartedRef.current) return;
    demoReplayStartedRef.current = false;
    if (typeof replayControls?.onStop === "function") {
      replayControls.onStop();
      return;
    }
    setFilmFullscreen(false);
    setCameraFollow(true);
    restoreShowLayers(maritimeLayers, filmLayerSnapRef.current);
    filmLayerSnapRef.current = null;
    replay.stop();
  }, [maritimeLayers, replay.stop, replayControls]);

  // Film de la visite arrêté depuis la barre (ou fini) : il n'appartient plus à la visite,
  // un film lancé ensuite par l'utilisateur ne sera pas coupé par Précédent / Quitter.
  useEffect(() => {
    if (!replay.active) demoReplayStartedRef.current = false;
  }, [replay.active]);

  const applyDemoAction = useCallback((action) => {
    if (action !== "replay") {
      stopDemoOwnedReplay();
      setDemoEditedPending(false);
    }
    const showFollow = (leftOpen, rightOpen) => {
      // selectView ne parque le dessin que s'il change de vue : un brouillon lancé
      // depuis la carte Berry en Suivre resterait armé (les clics ajouteraient des points).
      parkDrawing();
      if (view !== VIEW_SUIVRE) selectView(VIEW_SUIVRE);
      recaptureBoat();
      setCinemaMode(false);
      setFilmFullscreen(false);
      setHideFilmBar(false);
      setSidebarOpen(leftOpen);
      setToolsOpen(rightOpen);
    };

    switch (action) {
      case "welcome":
      case "models":
      case "live":
        showFollow(false, false);
        break;
      case "briefing":
        showFollow(true, false);
        break;
      case "layers":
        showFollow(false, true);
        break;
      case "replay":
        showFollow(true, false);
        break;
      case "trace":
        if (view !== VIEW_TRACER) selectView(VIEW_TRACER);
        // Drawing mode needs a free map; don't keep the camera locked to the boat.
        setCameraFollow(false);
        setCinemaMode(false);
        setFilmFullscreen(false);
        setHideFilmBar(false);
        setSidebarOpen(true);
        setToolsOpen(true);
        break;
      case "return":
        // Retour à Suivre sur la source actuelle. Pas de bascule vers Berry : avec une route
        // terminée, la carte Berry (pilule locale de Sidebar) et la carte ne seraient plus d'accord.
        // Un simple brouillon est mis de côté par parkDrawing (dans showFollow), jamais effacé.
        showFollow(true, false);
        break;
      default:
        break;
    }
  }, [parkDrawing, recaptureBoat, selectView, stopDemoOwnedReplay, view]);

  const startDemoReplay = useCallback(() => {
    if (replay.active || !replayControls?.canStart || typeof replayControls.onStart !== "function") return;
    demoReplayStartedRef.current = true;
    replayControls.onStart();
  }, [replay.active, replayControls]);

  // Un clic : choisir Rédigé (sans appel Nemotron, le rédigé existe déjà : hasWritten),
  // puis lancer le film dès que le plan rédigé est chargé (effet ci-dessous).
  const startDemoEditedReplay = useCallback(() => {
    if (!replayControls) return;
    setDemoEditedFellBack(false);
    if (!replay.hasWritten) {
      // Repli annoncé dans la visite : le Brut joue.
      setDemoEditedFellBack(true);
      startDemoReplay();
      return;
    }
    setDemoEditedPending(true);
    if (replay.filmStyle !== "written") replay.setFilmStyle("written");
  }, [replay.active, replay.hasWritten, replay.filmStyle, replay.setFilmStyle, replayControls, startDemoReplay]);

  const demoEditedNext = tourEditedStep({
    pending: demoEditedPending,
    active: replay.active,
    filmStyle: replay.filmStyle,
    loadedStyle: replay.filmLoadedStyle,
    remoteStatus: replay.remoteStatus,
    canStart: Boolean(replayControls?.canStart),
  });
  useEffect(() => {
    if (demoEditedNext === "idle" || demoEditedNext === "wait") return;
    setDemoEditedPending(false);
    // Le serveur a servi le Brut à la demande Rédigé : le repli est annoncé dans la visite.
    setDemoEditedFellBack(demoEditedNext === "raw");
    startDemoReplay();
  }, [demoEditedNext, startDemoReplay]);
  // Rédigé jamais servi dans le délai : retour au Brut, annoncé.
  useEffect(() => {
    if (!demoEditedPending) return undefined;
    const timer = setTimeout(() => {
      setDemoEditedFellBack(true);
      replay.setFilmStyle("raw");
    }, TOUR_EDITED_WAIT_MS);
    return () => clearTimeout(timer);
  }, [demoEditedPending, replay.setFilmStyle]);

  const closeDemo = useCallback(() => {
    setDemoEditedPending(false);
    setDemoEditedFellBack(false);
    stopDemoOwnedReplay();
    parkDrawing();
    if (view !== VIEW_SUIVRE) selectView(VIEW_SUIVRE);
    recaptureBoat();
    setCinemaMode(false);
    setFilmFullscreen(false);
    setHideFilmBar(false);
    setSidebarOpen(true);
    setToolsOpen(false);
  }, [parkDrawing, recaptureBoat, selectView, stopDemoOwnedReplay, view]);

  const fetchCustomPlan = useCallback((geojson) => {
    const applyFallback = () => setExpeditionPlan(buildLocalCustomBriefing(geojson, lang));
    setExpeditionPlan(null);
    const wps = waypointsFromCollection(geojson);
    const hasLine = (geojson?.features || []).some((f) => f?.geometry?.type === "LineString" && f.geometry.coordinates?.length >= 2);
    if (wps.length < 2 && !hasLine) { setBriefingLoading(false); applyFallback(); return; }
    const requestId = ++customFetchIdRef.current;
    setBriefingLoading(true);
    const finish = (plan) => {
      if (customFetchIdRef.current !== requestId || routeKindRef.current !== "custom") return;
      setExpeditionPlan(normalizeExpeditionPlan(plan));
      setBriefingLoading(false);
    };
    if (!ORCHESTRATOR_URL) { finish(buildLocalCustomBriefing(geojson, lang)); return; }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    fetch(`${ORCHESTRATOR_URL}/api/v1/expedition/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: lang, waypoints: wps }),
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`plan ${r.status}`))))
      .then((data) => finish(normalizeExpeditionPlan(data?.expedition_plan) || buildLocalCustomBriefing(geojson, lang)))
      .catch(() => finish(buildLocalCustomBriefing(geojson, lang)))
      .finally(() => clearTimeout(timer));
  }, [lang]);

  const handleCustomRoute = useCallback((geojson) => {
    berryFetchIdRef.current += 1;
    routeKindRef.current = "custom";
    setView(VIEW_TRACER);
    setCustomRoute(geojson);
    setRouteKind("custom");
    setVoyageFlat(null);
    setBriefingLoading(true);
    fetchCustomPlan(geojson);
    kickLayerWarm(geojson);
  }, [fetchCustomPlan]);

  // La pilule <ma route> bascule la SOURCE sans changer de mode :
  // en Suivre comme en Tracer, la route perso redevient celle qu'on dessine.
  const handleRouteSwitchToCustom = useCallback((geojson) => {
    if (!geojson) return;
    berryFetchIdRef.current += 1;
    routeKindRef.current = "custom";
    setCustomRoute(geojson);
    setRouteKind("custom");
    setVoyageFlat(null);
    setUserPreview(false);
    sceneApiRef.current?.playback.pause();
    setBriefingLoading(true);
    fetchCustomPlan(geojson);
    kickLayerWarm(geojson);
  }, [fetchCustomPlan]);

  // Ouvrir le dessin ne vide jamais le brouillon (points / segments).
  // Seuls Annuler et la suppression d'une route perso appellent reset.
  armDrawingWorldRef.current = (restoreView) => {
    const mapView = sceneApiRef.current?.getView();
    drawRestoreRef.current = {
      view: restoreView ?? view,
      center: mapView?.center || null,
      zoom: mapView?.zoom ?? null,
    };
    sceneApiRef.current?.playback.pause();
    setCinemaMode(false);
    setCameraFollow(false);
    setDrawingMode(true);
    berryFetchIdRef.current += 1;
    // Un brouillon vide garde le briefing Berry. On ne le
    // vide plus à l'ouverture du dessin ; le pin carte et la fiche d'escale
    // restent coupés.
    sceneApiRef.current?.briefing?.clear?.();
    setEscaleStop(null);
    if (replay.active) replay.stop();
    sceneApiRef.current?.beginDrawingWorld?.();
    requestAnimationFrame(() => sceneApiRef.current?.showWorld?.({ keepBoundsLifted: true }));
  };

  const handleDrawStart = () => {
    if (cinemaMode) {
      setSidebarOpen(cinemaSavedRef.current.sidebar);
      setToolsOpen(cinemaSavedRef.current.tools);
      setHideFilmBar(false);
    }
    armDrawingWorldRef.current(view);
  };

  const handleDrawCancel = () => {
    setDrawingMode(false);
    resetDrawState();
    closeSatellite();
    sceneApiRef.current?.endDrawingWorld?.();
    customFetchIdRef.current += 1;
    routeKindRef.current = "berry";
    setCustomRoute(null);
    setRouteKind("berry");
    setVoyageFlat(null);
    applyBerryBriefing();
    const prev = drawRestoreRef.current;
    if (prev.view && prev.view !== view) setView(prev.view);
    const mapView = sceneApiRef.current?.getView();
    if (mapView && prev.center) {
      sceneApiRef.current?.setView(prev.center, prev.zoom ?? mapView.zoom, { animate: false });
    }
  };

  const handleDrawFinish = () => {
    setDrawingMode(false);
    sceneApiRef.current?.endDrawingWorld?.();
    return drawingState.toGeoJson();
  };

  const handleImportRoute = useCallback(async (file) => {
    if (!file) return;
    let text = "";
    try {
      text = await file.text();
    } catch {
      setDrawNotice({ kind: "error", text: t("importRouteError") });
      return;
    }
    const parsed = parseRouteFile(text, file.name);
    if (parsed.error) {
      setDrawNotice({
        kind: "error",
        text: t(parsed.error === "noPoints" ? "noCoordsFound" : "importRouteError"),
      });
      return;
    }
    if (drawnPoints.length && !window.confirm(t("importRouteReplace"))) return;
    await handleImportPoints(parsed.points);
    if (parsed.truncated) setDrawNotice({ kind: "notice", text: t("importRouteTruncated", { max: DRAW_MAX_POINTS }) });
    else setDrawNotice(null);
    const map = sceneApiRef.current?.getMap?.();
    if (!map || !parsed.points.length) return;
    const latlngs = parsed.points.map((p) => [p.lat, p.lon]);
    if (latlngs.length === 1) {
      sceneApiRef.current.setView(latlngs[0], 6, { animate: false });
      return;
    }
    map.fitBounds(latlngs, { padding: [56, 56], maxZoom: 6, animate: false });
  }, [drawnPoints.length, handleImportPoints, t]);

  useEffect(() => {
    if (!drawNotice) return undefined;
    const id = setTimeout(() => setDrawNotice(null), 4000);
    return () => clearTimeout(id);
  }, [drawNotice]);

  // Dès un segment posé, chauffer AMP + perles minces du brouillon.
  // Debounce dans le warmer ; Annuler / supprimer (resetDrawState) coupent les vols.
  useEffect(() => {
    if (drawnPoints.length < 2) return undefined;
    draftWarmerRef.current.schedule(toGeoJson());
    return undefined;
  }, [drawnPoints, drawnSegments, toGeoJson]);

  const handleDrawContinue = () => {
    armDrawingWorldRef.current(view);
  };

  const handleCustomDelete = () => {
    customFetchIdRef.current += 1;
    routeKindRef.current = "berry";
    setCustomRoute(null);
    setRouteKind("berry");
    setVoyageFlat(null);
    resetDrawState();
    applyBerryBriefing();
  };

  useEffect(() => {
    const onEscDraw = (e) => {
      if (e.code !== "Escape" || !drawingMode) return;
      if (e.target?.closest?.("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      handleDrawCancel();
    };
    window.addEventListener("keydown", onEscDraw);
    return () => window.removeEventListener("keydown", onEscDraw);
  }, [drawingMode]);

  useEffect(() => {
    if (!drawingMode) return undefined;
    sceneApiRef.current?.beginDrawingWorld?.();
    const id = requestAnimationFrame(() => sceneApiRef.current?.showWorld?.({ keepBoundsLifted: true }));
    return () => cancelAnimationFrame(id);
  }, [drawingMode]);

  useEffect(() => {
    if (routeKind !== "berry" || drawingMode) return;
    setExpeditionPlan(getCachedPlan(lang) || normalizeExpeditionPlan({ executive_briefing: t("berryLocalBriefing") }));
    if (!ORCHESTRATOR_URL) return;
    const requestId = ++berryFetchIdRef.current;
    fetch(`${ORCHESTRATOR_URL}/api/v1/expedition/plan/berry-mappemonde`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: lang,
        waypoints: ITINERARY_POINTS.map((p) => ({
          name: p.name, lat: p.lat, lon: p.lon, type: p.flag ? "escale_obligatoire" : "point_intermediaire",
        })),
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (routeKindRef.current !== "berry" || berryFetchIdRef.current !== requestId) return;
        const plan = normalizeExpeditionPlan(data?.expedition_plan);
        if (plan) {
          setExpeditionPlan(plan);
          setCachedPlan(lang, plan);
        }
      })
      .catch(() => {});
  }, [lang, routeKind, drawingMode, t]);

  useEffect(() => {
    if (routeKind !== "custom" || drawingMode || !customRoute) return;
    fetchCustomPlan(customRoute);
  }, [lang]);

  useEffect(() => { setPoints(ITINERARY_POINTS); }, []);

  useEffect(() => {
    if (!points.length) return undefined;
    const legs = buildBerryLegs(points);
    let cancelled = false;
    (async () => {
      setLoading(true);
      setOfficialFallback(false);
      try {
        // La route Berry est déjà dans le fichier (routeur + contrôle de terre).
        // On la charge. searoute ne sert que si ce fichier manque.
        const official = await loadOfficialBerryRoute();
        if (cancelled) return;
        setSegments(official.segments);
        setOfficialFallback(false);
        setLoading(false);
        setSegProgress({ done: official.segments.length, total: official.segments.length });
        return;
      } catch { /* searoute si le geojson officiel manque */ }
      setSegProgress({ done: 0, total: legs.length });
      const accumulated = [];
      const fetchLeg = async (leg) => {
        if (isNonMaritimeLeg(leg.from.name, leg.to.name)) {
          return { ...leg, coords: [[leg.from.lon, leg.from.lat], [leg.to.lon, leg.to.lat]], nonMaritime: true };
        }
        if (isAirLegNames(leg.from.name, leg.to.name)) {
          return {
            ...leg,
            coords: [[leg.from.lon, leg.from.lat], [leg.to.lon, leg.to.lat]],
            nonMaritime: false,
            air: true,
          };
        }
        try {
          const params = new URLSearchParams({
            start_lat: leg.from.lat, start_lon: leg.from.lon, end_lat: leg.to.lat, end_lon: leg.to.lon, check_wind: false,
          });
          const res = await fetch(`${API_URL}/route?${params}`);
          if (!res.ok) return { ...leg, coords: [], error: `HTTP ${res.status}` };
          const data = await res.json();
          const coords = orientCoords(coordsFromRoutePayload(data), leg.from, leg.to);
          if (!coords.length) return { ...leg, coords: [], error: "empty route" };
          return { ...leg, coords, nonMaritime: false };
        } catch (e) {
          return { ...leg, coords: [], error: e.message };
        }
      };
      for (let i = 0; i < legs.length && !cancelled; i += SEGMENT_BATCH_SIZE) {
        const batch = await Promise.all(legs.slice(i, i + SEGMENT_BATCH_SIZE).map(fetchLeg));
        accumulated.push(...batch);
        if (!cancelled) {
          setSegments(accumulated.filter((r) => r.coords?.length));
          setSegProgress({ done: Math.min(i + SEGMENT_BATCH_SIZE, legs.length), total: legs.length });
          if (i === 0) setLoading(false);
        }
      }
      if (!cancelled) {
        setOfficialFallback(accumulated.every((r) => r.nonMaritime || !r.coords?.length || r.error));
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [points]);

  const handleMapRouteClick = useCallback((position) => {
    fetchSatellite(position.lat, position.lon);
  }, [fetchSatellite]);

  const handleSaveDrawPointMeta = () => {
    if (selectedSatellite?.drawPointIndex != null) {
      drawingState.updatePoint(selectedSatellite.drawPointIndex, { name: pointInfoName.trim() || undefined, flags: pointInfoFlags.filter(Boolean) });
    }
    setSelectedSatellite(null);
  };

  const drawingMessage = drawnPoints.length === 0 ? t("drawStart") : drawnPoints.length === 1 ? t("drawFirstStop") : t("drawNextStop");
  // What the drawn route is so far — the boxes describe it, not the official route.
  const drawing = useMemo(() => {
    if (!drawingMode) return null;
    const nm = legsDistanceNm(drawnSegments);
    return {
      points: drawnPoints.map((p, i) => ({ name: p.name || `${t("drawPointLabel")} ${i + 1}`, lat: p.lat, lon: p.lon })),
      distanceNm: Math.round(nm),
      segments: drawnSegments.length,
      loading: drawingLoading,
      message: drawingMessage,
      notice: drawingNotice?.code || null,
    };
  }, [drawingMode, drawnPoints, drawnSegments, drawingLoading, drawingMessage, drawingNotice, t]);

  useEffect(() => {
    if (!drawingNotice?.code) return;
    const key = drawingNotice.code === "on_land"
      ? "pointOnLand"
      : drawingNotice.code === "limit"
        ? "drawPointLimitReached"
        : drawingNotice.code === "busy"
          ? "routeServerBusy"
          : drawingNotice.code === "server_error"
            ? "routeServerError"
            : drawingNotice.code === "network_error"
              ? "routeNetworkError"
              : "rhumbCrossesLand";
    setDrawNotice({ kind: drawingNotice.code === "limit" ? "notice" : "error", text: t(key, { max: DRAW_MAX_POINTS }) });
  }, [drawingNotice, t]);
  const statsSegs = useMemo(
    () => (routeForView ? featuresToSegments(routeForView) : segments),
    [routeForView, segments],
  );
  const stats = useMemo(() => routeStats(statsSegs), [statsSegs]);
  const statsPoints = useMemo(
    () => (routeForView
      ? (routeForView.features || []).filter((f) => f.geometry?.type === "Point").map((f) => ({
        name: f.properties?.name || "", lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], flag: "",
      }))
      : points),
    [routeForView, points],
  );
  const toggleSidebar = useCallback(() => setSidebarOpen((open) => !open), []);
  const toggleTools = useCallback(() => setToolsOpen((open) => !open), []);
  const handleSidebarSeek = useCallback((nm) => {
    noteClockMove();
    if (isSuivre) setUserPreview(true);
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(nm, { jump: true });
  }, [isSuivre, sceneApi, noteClockMove]);
  const handleSeekJournal = useCallback((iso) => {
    const sample = sampleClockAtTime(officialClock, iso);
    const nm = Number(sample?.filmNm);
    if (!Number.isFinite(nm)) return;
    noteClockMove();
    if (isSuivre) setUserPreview(true);
    sceneApiRef.current?.playback.pause();
    sceneApiRef.current?.playback.seek(nm, { jump: true });
  }, [officialClock, isSuivre, sceneApi, noteClockMove]);
  // Revue de plan par règles: legs from the server (clock + pearls), season from the atlas cache.
  const planReviewState = usePlanReview({
    // GET /voyage/official/plan-review (et /eta) seulement en
    // Suivre × Berry. Tracer et Suivre × ma route gardent le repli local.
    enabled: Boolean(suivreBerry && officialClock),
    frozen: replay.active,
    clock: officialClock,
    nowMs: clockNowMs,
    liveFilmNm: legendLiveFilmNm,
    officialEta: officialEtaReady,
    lookup: atlas.lookup,
    revision: atlas.revision,
    lang,
    galeLimitPct: skipper.orders?.values?.galePct,
  });
  // Route advice under the skipper's orders: gale and sea limits of
  // the resolved orders become no-go zones of the isochrone.
  const handleRecompute = useCallback(
    () => vessel.recompute(clockSample?.iso, {
      windMaxKt: skipper.orders?.values?.galeKt,
      hsMaxM: skipper.orders?.values?.hsAlertM,
    }),
    [vessel.recompute, clockSample?.iso, skipper.orders?.values?.galeKt, skipper.orders?.values?.hsAlertM],
  );
  const customReviewLegs = useMemo(
    () => (suivreCustom ? legsFromClockMarks(voyage.clock, lang) : []),
    [suivreCustom, voyage.clock, lang],
  );
  const planReview = useMemo(() => ({
    legs: suivreCustom ? customReviewLegs : planReviewState.legs,
    loading: suivreCustom ? false : planReviewState.loading,
    error: planReviewState.error,
    summary: null,
    comment: suivreCustom ? null : (planReviewState.review?.comment?.text || null),
    commentSource: suivreCustom ? null : (planReviewState.review?.comment?.source || null),
    advice: suivreCustom ? null : planReviewState.advice,
    onApply: handleRecompute,
  }), [suivreCustom, customReviewLegs, planReviewState.legs, planReviewState.loading, planReviewState.error, planReviewState.review, planReviewState.advice, handleRecompute]);
  const mapScene = useMemo(() => ({
    isLightMode,
    view,
    isTracer,
    isSuivre,
    routeReady,
    sceneReady,
    segments,
    points,
    // La scène dessine la source courante et seulement elle : la route
    // perso quand elle est choisie (dans les deux modes), la Berry sinon.
    customRoute: routeForView,
    drawingMode,
    drawnPoints,
    drawnSegments,
    flat: flatRoute,
    marks: escaleMarks,
    stops: activeStops,
    boatKnots,
    stopAuto: isTracer && stopAuto,
    live,
    previewing,
    draft: vessel.draft,
    grib: official.grib,
    gribStatus: official.gribStatus,
    clockSample,
    clockVertices: officialClock?.vertices || null,
    traveledNm: isSuivre && live && !previewing
      ? (Number(live.sailNm) || Number(live.filmNm) || 0)
      : (cast?.sailNm ?? playback.nm),
    climoMonth,
    lang,
    t,
    cameraFollow,
    cinemaRecapture,
    cameraFocusToken: isTracer ? cameraFocusToken : 0,
    remainingNm: hudLeg?.remainingNm ?? playback.sailTotalNm,
    recetteMap: recetteMapView(),
    filmActive: Boolean(replay.active),
    filmChapterIdx: replay.chapterIdx,
    filmLeg: replay.filmLeg,
  }), [
    isLightMode,
    view,
    isTracer,
    isSuivre,
    routeReady,
    sceneReady,
    segments,
    points,
    routeForView,
    drawingMode,
    drawnPoints,
    drawnSegments,
    flatRoute,
    escaleMarks,
    activeStops,
    boatKnots,
    stopAuto,
    live,
    previewing,
    vessel.draft,
    official.grib,
    official.gribStatus,
    clockSample,
    officialClock?.vertices,
    cast?.sailNm,
    playback.nm,
    climoMonth,
    lang,
    t,
    cameraFollow,
    cinemaRecapture,
    cameraFocusToken,
    hudLeg?.remainingNm,
    playback.sailTotalNm,
    replay.active,
    replay.chapterIdx,
    replay.filmLeg,
  ]);

  const enablePendingRestricted = (kind) => {
    // commit écrit l'état brut : Accepter allume tout de suite, vue monde comprise.
    const commit = gateRef.current?.commit;
    if (typeof commit === "function") {
      commit(kind);
      return;
    }
    if (kind === "balisage") maritimeLayers.setShowBalisage(true);
    else if (kind === "bathymetry") maritimeLayers.setShowBathymetry(true);
    else if (kind === "fonds") maritimeLayers.setShowFonds(true);
    else if (kind === "cables") maritimeLayers.setShowCables(true);
  };

  useLayoutEffect(() => {
    if (!filmBarNode) {
      setFilmBarMeasuredPx(null);
      return undefined;
    }
    const publish = () => {
      setFilmBarMeasuredPx(measureFilmBarOccupiedPx(filmBarNode));
    };
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(filmBarNode);
    window.addEventListener("resize", publish);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", publish);
    };
  }, [filmBarNode]);

  const rootInsetVars = mapInsetVars({
    sidebarOpen: sidebarOpen && !filmFullscreen,
    toolsOpen: toolsOpen && !filmFullscreen,
    filmBarVisible: true,
    filmBarControls: isTracer,
    filmBarMeasuredPx,
  });

  return (
    <div
      data-testid="sim-root"
      style={{ height: "100vh", width: "100vw", position: "relative", ...rootInsetVars }}
      className={`${isLightMode ? "light-mode" : ""}${filmFullscreen ? " film-fullscreen" : ""}`.trim()}
    >
      <MapScene
        scene={mapScene}
        gateRef={gateRef}
        onReady={handleSceneReady}
        onPlayback={handleScenePlayback}
        onLayerState={handleLayerState}
        onClimatologyState={handleClimatologyState}
        onFeature={onFeature}
        onCameraPlaced={setCameraPlaced}
        onManualNavigation={() => setCameraFollow(false)}
        onDrawingClick={handleDrawingClick}
        onRouteClick={handleMapRouteClick}
        onBoatDrag={handleCatamaranDrag}
        onCoordinatesCopied={handleCoordinatesCopied}
        onWaypointHover={setHoveredPoint}
        onDrawingWaypointClick={handleDrawingWaypointClick}
        onWaypointClick={openEscaleFromUi}
      />

      <NotForNavModal
        open={notForNavOpen}
        onCancel={() => { pendingLayerRef.current = null; setNotForNavOpen(false); }}
        onAccept={() => {
          const kind = pendingLayerRef.current;
          writeNotForNavAccepted();
          gateRef.current.allowed = true;
          setNotForNavOk(true);
          setNotForNavOpen(false);
          enablePendingRestricted(kind);
          pendingLayerRef.current = null;
        }}
      />
      <PanelBoundary>
      <PanelCrashProbe panel="sidebar" />
      <Sidebar
        plan={expeditionPlan}
        open={sidebarOpen}
        onToggle={toggleSidebar}
        onCustomRoute={handleCustomRoute}
        onRouteSwitchToBerry={handleRouteSwitchToBerry}
        onRouteSwitchToCustom={handleRouteSwitchToCustom}
        isDrawing={drawingMode}
        onDrawStart={handleDrawStart}
        onDrawContinue={handleDrawContinue}
        onDrawFinish={handleDrawFinish}
        onDrawCancel={handleDrawCancel}
        onCustomDelete={handleCustomDelete}
        canContinueDraw={drawnPoints.length > 0}
        canFinishDraw={canFinishDrawnRoute(drawnPoints.length, drawnSegments.length, drawingLoading, drawingNotice?.code)}
        drawing={drawing}
        onDrawUndo={handleDrawUndo}
        onImportRoute={handleImportRoute}
        importBusy={drawingLoading}
        isCockpit={false}
        polarData={polarData}
        briefingLoading={iciPack.loading || briefingLoading}
        officialFallback={officialFallback}
        iciBriefing={iciPack.briefing}
        iciBriefingSegments={iciPack.briefingSegments}
        todayPosition={Boolean(iciPack.todayPosition)}
        onBriefingFocus={handleBriefingFocus}
        journal={officialJournal.journal}
        journalLoading={officialJournal.loading}
        journalError={officialJournal.error}
        story={storyParagraphs}
        storyReplay={replay.active}
        skipperNotice={skipper.notice}
        view={view}
        legContext={sidebarHudLeg}
        nowLeg={replay.active && hudLeg?.fromStop ? {
          fromStop: hudLeg.fromStop,
          toStop: hudLeg.toStop,
          speedKnots: hudLeg.speedKnots,
          remainingNm: hudLeg.nmRemainingToStop ?? hudLeg.remainingNm,
        } : nowLeg}
        replayFrame={replayFrame}
        clockSample={sidebarClockSample}
        atQuay={atQuay}
        quayDays={quayDays}
        previewing={previewing}
        forecastStatus={isSuivre && official.gribStatus === "ready" ? "ready" : null}
        onRecompute={handleRecompute}
        canRecompute={canRecompute}
        recomputeBusy={vessel.busy}
        onGoLive={goLive}
        momentNow={replay.active ? replay.card : (sceneReady ? moments.now : null)}
        momentNowLeft={replay.active ? 0 : moments.nowLeft}
        onMomentDismiss={replay.active ? replay.dismissCard : moments.dismiss}
        momentFree={sceneReady && !replay.active ? moments.free : null}
        momentFreeLeft={moments.freeLeft}
        onMomentNext={moments.next}
        chat={chat}
        onChatAsk={chat.ask}
        moment={iciMoment.moment}
        momentHighSeasRuledOut={momentHighSeasRuled}
        journalEntries={momentJournal.entries}
        onSeek={handleSeekJournal}
        momentMode={momentMode}
        routeSource={routeSource}
        planReview={planReview}
        escaleStop={replay.active ? null : escaleStop}
        escaleFiche={escaleSheet?.fiche}
        escaleLoading={Boolean(escaleSheet?.loading)}
        escaleError={escaleSheet?.error}
        onEscaleClose={closeEscaleSheet}
      />
      </PanelBoundary>

      <PanelBoundary>
      <ToolsSidebar
        segments={statsSegs}
        points={statsPoints}
        open={toolsOpen}
        onToggle={toggleTools}
        isLightMode={isLightMode}
        onLightModeChange={setIsLightMode}
        polarData={polarData}
        onPolarDataLoaded={setPolarData}
        routeDistanceNm={stats.nm}
        routeSegmentCount={stats.segments}
        maritimeLayers={{
          ...maritimeLayers,
          loadingClimoWind: climoLayer.loading && maritimeLayers.showClimoWind,
          loadingClimoWave: climoLayer.loading && maritimeLayers.showClimoWave,
          loadingClimoCurrent: climoLayer.loading && maritimeLayers.showClimoCurrent,
          loadingClimoCyclones: climoLayer.loading && maritimeLayers.showClimoCyclones,
          errorClimatology: climoLayer.error,
        }}
        escaleMarks={legendMarks}
        filmNm={sidebarPlaybackNm}
        nowMs={clockNowMs}
        liveFilmNm={legendLiveFilmNm}
        officialEta={officialEtaReady}
        onEscaleSheet={openEscaleFromUi}
        frozen={Boolean(replay.active)}
        drawing={drawing}
        showDeparture={isSuivre}
        departureT0={suivreBerry ? replayT0 : voyage.t0}
        onDepartureT0={suivreBerry ? setReplayT0 : voyage.setT0}
        skipperOrders={skipper.orders}
        skipperProfile={skipper.profile}
        onSkipperProfile={skipper.setProfile}
        onSkipperComfort={skipper.setComfort}
        onSkipperHorizon={skipper.setHorizon}
        onSkipperExpert={skipper.setExpert}
        onSkipperBoat={skipper.setBoat}
        onSkipperReset={skipper.reset}
        skipperSuggest={skipper.suggest}
        onSkipperSuggestAccept={skipper.acceptSuggest}
        onSkipperSuggestDismiss={skipper.dismissSuggest}
        exportMode={viewExportMode(drawingMode, isSuivre)}
        exportSegments={drawingMode ? drawnSegments : activeSegments}
        exportPoints={drawingMode ? drawnPoints : legendMarks}
        tracerLayout={!isSuivre}
        ampNearby={iciPack.dossier?.amp || []}
      />
      </PanelBoundary>

      {!sceneReady && !drawingMode && (
        <div data-testid="scene-load-mask" className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm flex flex-col items-center justify-center z-[1500] pointer-events-none">
          <div className="w-10 h-10 border-4 border-blue-400/30 border-t-blue-400 rounded-full animate-spin" />
          <div className="mt-4 text-white/90 text-sm font-medium">{t(sceneMaskKey({ routeReady }))}</div>
        </div>
      )}

      {!sceneReady && !drawingMode && segProgress.done < segProgress.total && (
        <div className="absolute bottom-20 right-5 z-20 flex items-center gap-2 bg-slate-900/90 text-white text-xs font-medium px-3 py-2 rounded-full shadow-lg pointer-events-none">
          <div className="w-3.5 h-3.5 border-2 border-blue-400/40 border-t-blue-400 rounded-full animate-spin" />
          <span>{t("routesProgress", { done: segProgress.done, total: segProgress.total })}</span>
        </div>
      )}

      {drawingMode && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-[2100] pointer-events-none">
          <div className="flex flex-col items-center gap-1">
            <div className="flex items-center gap-2 bg-slate-900/95 border border-green-500/50 text-white text-sm font-semibold px-4 py-2.5 rounded-full shadow-2xl">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span>{drawingMessage}</span>
              <span data-testid="draw-point-limit" className="text-[11px] font-medium text-white/70">{t("drawPointLimit", { max: DRAW_MAX_POINTS })}</span>
              {drawingLoading && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              <div className="flex gap-1 ml-1 pointer-events-auto">
                <button type="button" onClick={handleDrawUndo} disabled={!drawnPoints.length} className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 disabled:opacity-30" title={t("undoLastPoint")}><Undo2 size={13} /></button>
                <button type="button" onClick={handleDrawRedo} disabled={!canRedo} className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 disabled:opacity-30" title={t("redo")}><Redo2 size={13} /></button>
                <button type="button" onClick={handleDrawCancel} className="h-7 px-2 rounded-full bg-white/10 text-[11px] font-semibold" title={t("cancel")}>{t("cancel")}</button>
              </div>
            </div>
            {drawNotice && (
              // Under the drawing pill, above the map and the panels: a point
              // refused (on land, limit) is always said, never silently dropped.
              <div
                role="status"
                data-testid={drawNotice.kind === "error" ? "route-import-error" : "route-import-notice"}
                className={`border text-[11px] font-semibold px-3 py-1 rounded-full shadow-lg ${
                  drawNotice.kind === "error"
                    ? "bg-rose-950/95 border-rose-400/60 text-rose-50"
                    : "bg-slate-900/95 border-sky-400/50 text-sky-50"
                }`}
              >
                {drawNotice.text}
              </div>
            )}
          </div>
        </div>
      )}

      {clipboardToast && (
        <div className="absolute top-5 left-1/2 -translate-x-1/2 z-30 bg-slate-900/95 text-white text-xs px-4 py-2 rounded-full">
          📋 {clipboardToast} {t("copied")}
        </div>
      )}
      {drawNotice && !drawingMode && (
        <div
          role="status"
          data-testid={drawNotice.kind === "error" ? "route-import-error" : "route-import-notice"}
          className="absolute top-16 left-1/2 -translate-x-1/2 z-[2100] bg-slate-900/95 text-white text-xs px-4 py-2 rounded-full pointer-events-none"
        >
          {drawNotice.text}
        </div>
      )}

      {hoveredPoint && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-20 bg-slate-900/90 text-white text-xs px-3 py-1.5 rounded-full pointer-events-none">
          {hoveredPoint.name}
        </div>
      )}

      {climoAnyOn && (
        <div
          data-testid="climatology-banner"
          className="naviguide-climo-banner absolute left-1/2 -translate-x-1/2 z-20 bg-sky-950/90 border border-sky-400/40 text-sky-100 text-xs px-4 py-2 rounded-full bottom-48 pointer-events-none"
        >
          {t("climatologyOn", { month: monthLabel || String(climoMonth), maps: climoMapsLabel })}
          {climoLayer.counts && (
            <span className="ml-2 opacity-80" data-testid="climatology-overlay-ready">
              {[
                maritimeLayers.showClimoWind && `roses ${climoLayer.counts.wind || 0}`,
                maritimeLayers.showClimoWave && `P50 ${climoLayer.counts.waveP50 || 0}`,
                maritimeLayers.showClimoWave && `P90 ${climoLayer.counts.waveP90 || 0}`,
                maritimeLayers.showClimoWave && climoLayer.counts.waveMean ? `Hs mean ${climoLayer.counts.waveMean}` : null,
                maritimeLayers.showClimoCurrent && `courant ${climoLayer.counts.current || 0}`,
                maritimeLayers.showClimoCyclones && `IBTrACS ${climoLayer.counts.cyclones || 0}`,
              ].filter(Boolean).join(" · ")}
              {climoLayer.source === "global" && (
                <span data-testid="climatology-source">{` · ${t("climatologySourceGlobal")}`}</span>
              )}
            </span>
          )}
          {climoLayer.error === "atlas_empty" && atlas.alive === false && (
            <span className="ml-2 text-amber-200">{t("climatologyAtlasDown")}</span>
          )}
        </div>
      )}

      <ReplayErrorBoundary>
      <SimulationFilmBar
        ref={filmBarRef}
        barRef={filmBarRef}
        fromName={hudLeg?.fromStop}
        toName={hudLeg?.toStop}
        finished={Boolean(hudLeg?.finished)}
        nm={isSuivre && live && !previewing ? (live.sailNm ?? cast?.sailNm ?? 0) : (cast?.sailNm ?? 0)}
        totalNm={playback.sailTotalNm || flatRoute.totalNm}
        playhead={isSuivre && live && !previewing ? (Number(live.filmNm) || playback.nm) : playback.nm}
        playheadTotal={playback.totalNm}
        remainingNm={hudLeg?.remainingNm ?? 0}
        etaHours={hudLeg?.etaHours}
        boatKnots={displayKnots}
        phase={cast?.phase}
        vehicle={cast?.vehicle}
        profile={playback.profile}
        onProfile={(profile) => sceneApiRef.current?.playback.setProfile(profile)}
        playing={playback.playing}
        onTogglePlay={() => {
          if (!playControlsActive) return;
          if (isSuivre) setUserPreview(true);
          if (
            isTracer
            && playheadOnPlay(playback.nm, playback.totalNm) === 0
            && (Number(playback.nm) || 0) > 1
          ) {
            voyage.resetToToday();
          }
          noteClockMove();
          sceneApiRef.current?.playback.toggle();
        }}
        marks={escaleMarks}
        onSeekNm={(nm) => {
          if (!playControlsActive) return;
          noteClockMove();
          if (isSuivre) setUserPreview(true);
          sceneApiRef.current?.playback.pause();
          sceneApiRef.current?.playback.seek(nm, { jump: true });
        }}
        onPrev={handleSimPrev}
        canPrev={canPrevEscale(escaleMarks, playback.nm)}
        onNext={handleSimNext}
        canNext={canNextEscale(escaleMarks, playback.nm)}
        showPlaybackControls={playControlsActive}
        cinema={cinemaMode}
        onCinema={toggleCinema}
        hideBar={hideFilmBar}
        onHideBar={setHideFilmBar}
        liveSpeed={expeditionSpeed.live}
        windSeries={windProfile.series}
        windLoading={windProfile.loading}
        holding={playback.holding}
        clockLine={clockLine}
        atQuay={atQuay}
        quayDays={quayDays}
        twa={clockSample?.twa}
        liveStatus={isSuivre ? (previewing ? t("previewBadge") : "LIVE") : null}
        windKind={clockSample?.kind === "forecast" ? "forecast" : (suivreBerry ? null : (clockSample?.kind || expeditionSpeed.kind))}
        weatherLine={weatherLine}
        showSpeeds={playControlsActive}
        showWindProfile={false}
        stopAuto={stopAuto}
        onStopAuto={setStopAuto}
        showStopAuto={isTracer}
        sidebarOpen={sidebarOpen && !filmFullscreen}
        toolsOpen={toolsOpen && !filmFullscreen}
        filmFullscreen={filmFullscreen}
        onFilmFullscreen={setFilmFullscreen}
        eventMarks={filmEventMarks(iciPack.events, { mode: isSuivre ? "suivre" : SERVER_MODE_TRACER })}
        onEventClick={(ev) => {
          setSkipperClickId(ev.id || ev.stableKey);
          if (!isTracer || !Number.isFinite(ev.filmCum)) return;
          noteClockMove();
          sceneApiRef.current?.playback.pause();
          sceneApiRef.current?.playback.seek(ev.filmCum, { jump: true });
        }}
        storiesPending={(iciPack.events || []).filter((e) => e.story?.status === "pending").length}
        speechText={speechText}
        replay={replayControls}
        drawing={drawing}
        view={view}
        onView={selectView}
        gribLine={suivreBerry && official.gribStatus !== "ready" && official.gribStatus !== "pending" ? t("gribMissing") : ""}
        clock={officialClock}
        clockCurrent={clockSample ? {
          filmNm: isSuivre && live && !previewing ? (Number(live.filmNm) || 0) : playback.nm,
          sailNm: clockSample.sailNm,
          seaHours: clockSample.seaHours,
          regime: clockSample.regime || clockSample.kind,
          sources: clockSample.sources || [],
          spread: clockSample.spread,
        } : null}
        disclaimer={t("creditsLine")}
      />
      </ReplayErrorBoundary>

      <RecomputeDialog
        draft={vessel.draft}
        busy={vessel.busy}
        onAccept={async () => { await vessel.accept(); }}
        onReject={() => vessel.reject()}
      />

      <EscalePopupHost
        stop={replay.active ? null : escaleStop}
        fiche={escaleSheet?.fiche}
        loading={Boolean(escaleSheet?.loading)}
        error={escaleSheet?.error}
        onClose={closeEscaleSheet}
        onFocus={handleBriefingFocus}
      />
      <LayerFichePopup popup={layerPopup} onClose={() => setLayerPopup(null)} />

      <DemoWalkthrough
        replayReady={Boolean(replayControls?.canStart)}
        replayActive={Boolean(replay.active)}
        customRoute={routeSource === "custom"}
        hidden={filmFullscreen || notForNavOpen}
        isLightMode={isLightMode}
        autoStart={tourFromUrl}
        onStepChange={applyDemoAction}
        onPlayReplay={startDemoReplay}
        editedReady={Boolean(replay.hasWritten)}
        editedSource={replay.hasWritten ? t(filmSourceKey(replay.filmSource, replay.filmReviewedBy, replay.filmModel)) : ""}
        editedPending={demoEditedPending}
        editedFellBack={demoEditedFellBack}
        onPlayEdited={startDemoEditedReplay}
        onClose={closeDemo}
      />

      {selectedSatellite && (
        <div data-testid="satellite-popup" className="naviguide-floating-card absolute left-1/2 -translate-x-1/2 z-[2100] w-[360px] bg-slate-900/96 border border-white/10 rounded-xl p-3 text-white text-xs shadow-2xl bottom-52">
          <button type="button" data-testid="satellite-popup-close" className="absolute top-2 right-2 text-slate-400" aria-label={t("satellitePopupClose")} onClick={closeSatellite}><X size={14} /></button>
          <div className="font-semibold mb-2">{t("satelliteData")}</div>
          <div className="flex gap-1 mb-2">
            {["wind", "waves", "currents"].map((tab) => (
              <button key={tab} type="button" data-testid={`satellite-tab-${tab}`} onClick={() => setSatelliteTab(tab)} className={`px-2 py-1 rounded ${satelliteTab === tab ? "bg-blue-600" : "bg-slate-800"}`}>
                {tab === "wind" ? t("windTab") : tab === "waves" ? t("wavesTab") : t("currentsTab")}
              </button>
            ))}
          </div>
          {satelliteTab === "wind" && (
            productHasData(selectedSatellite.wind, "wind")
              ? <SatelliteMetPanel kind="wind" product={selectedSatellite.wind} t={t} lang={lang} />
              : <p>{satelliteLoading || selectedSatellite.wind?.status === "pending" ? t("fetchingSatellite") : t("noWindData")}</p>
          )}
          {satelliteTab === "waves" && (
            productHasData(selectedSatellite.wave, "wave")
              ? <SatelliteMetPanel kind="wave" product={selectedSatellite.wave} t={t} lang={lang} />
              : <p>{satelliteLoading || selectedSatellite.wave?.status === "pending" ? t("fetchingSatellite") : t("noWaveData")}</p>
          )}
          {satelliteTab === "currents" && (
            productHasData(selectedSatellite.current, "current")
              ? <SatelliteMetPanel kind="current" product={selectedSatellite.current} t={t} lang={lang} />
              : <p>{satelliteLoading || selectedSatellite.current?.status === "pending" ? t("fetchingSatellite") : t("noCurrentData")}</p>
          )}
          {selectedSatellite.drawPointIndex != null && (
            <div className="mt-2 border-t border-white/10 pt-2">
              <label className="block text-slate-400 mb-1">{t("waypointName")}</label>
              <input value={pointInfoName} onChange={(e) => setPointInfoName(e.target.value)} className="w-full bg-slate-800 rounded px-2 py-1" placeholder={t("waypointNamePlaceholder")} />
              <button type="button" onClick={handleSaveDrawPointMeta} className="mt-2 w-full bg-blue-600 rounded py-1">{t("saveClose")}</button>
            </div>
          )}
        </div>
      )}

      {carnetOpen ? (
        <CarnetDeBord
          title={t("carnetTitle")}
          storyLabel={t("carnetStory")}
          journalLabel={t("carnetJournal")}
          backLabel={t("carnetBack")}
          backHref={mapPageHref(typeof window !== "undefined" ? window.location.search : "")}
          chapters={storyParagraphs}
          entries={momentJournal.entries}
          lang={lang}
        />
      ) : null}

    </div>
  );
}
