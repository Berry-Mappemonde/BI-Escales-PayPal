import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";

const src = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(join(src, path), "utf8");

describe("contrat UI produit", () => {
  it("Démarre en Suivre cinéma, vue monde, panneaux fermés", () => {
    const app = read("../App.jsx");
    const map = read("../hooks/useSimulatorMap.js");
    const scene = read("../map/MapSceneController.js");
    assert.match(app, /const \[view, setView\] = useState\(VIEW_SUIVRE\)/);
    assert.doesNotMatch(app, /const \[view, setView\] = useState\(VIEW_TRACER\)/);
    assert.match(app, /const \[cinemaMode, setCinemaMode\] = useState\(true\)/);
    assert.match(app, /const \[sidebarOpen, setSidebarOpen\] = useState\(false\)/);
    assert.match(app, /const \[toolsOpen, setToolsOpen\] = useState\(false\)/);
    assert.match(map, /zoom:\s*2/);
    assert.match(scene, /WORLD_ZOOM = 2/);
    assert.match(scene, /zoom: WORLD_ZOOM/);
    assert.doesNotMatch(app, /map\.setView\(\[start\.lat,\s*start\.lon\],\s*8/);
    const tools = read("../components/ToolsSidebar.jsx");
    assert.match(tools, /visibility: open \? "visible" : "hidden"/, "Cinéma : le panneau droit n'est pas peint fermé");
  });

  it("Entrée Tracer ouvre le dessin sans vider le brouillon", () => {
    const app = read("../App.jsx");
    const sidebar = read("../components/Sidebar.jsx");
    const selectAt = app.indexOf("const selectView = useCallback");
    assert.ok(selectAt >= 0, "selectView présent");
    const selectChunk = app.slice(selectAt, selectAt + 2800);
    assert.match(selectChunk, /armDrawingWorldRef\.current\(VIEW_TRACER\)/);
    assert.match(selectChunk, /endDrawingWorld|parkDrawing\(\)/);
    assert.match(app, /onView=\{selectView\}/);
    assert.doesNotMatch(app, /onView=\{drawingMode \? undefined/);
    assert.match(sidebar, /startOrResumeDraw/);
    assert.match(sidebar, /canContinueDraw \? onDrawContinue : onDrawStart/);
    assert.match(sidebar, /drawingOn \? pillOn : pillOff/);
  });

  it("Dessin ouvert = cadre « Tracé en cours » toujours là, légende dessous à brouillon vide", () => {
    const app = read("../App.jsx");
    const tools = read("../components/ToolsSidebar.jsx");
    // Plus de contournement showBox : le cadre dépend du seul état du dessin.
    assert.doesNotMatch(app, /drawBoxOpen|showBox/);
    assert.doesNotMatch(tools, /showBox/);
    // Dès le premier point, le cadre remplace l'expédition ; à 0 point il la précède (RE2 gardée).
    assert.match(tools, /if \(drawing\?\.points\?\.length\) return <DrawingBox drawing=\{drawing\} \/>;/);
    assert.match(tools, /\{drawing \? <DrawingBox drawing=\{drawing\} \/> : null\}\s*<div[^>]*data-testid="expedition-box"/);
  });

  it("Entrée Tracer pose la vue monde", () => {
    const app = read("../App.jsx");
    const scene = read("../map/MapSceneController.js");
    assert.match(app, /sceneApiRef\.current\?\.showWorld/);
    assert.match(scene, /showWorld\(/);
    assert.match(scene, /setView\(WORLD_CENTER, worldZ/);
  });

  it("Suivre → Simulation quitte le Cinéma et ouvre les deux panneaux", () => {
    const app = read("../App.jsx");
    const selectAt = app.indexOf("const selectView = useCallback");
    assert.ok(selectAt >= 0, "selectView présent");
    const selectChunk = app.slice(selectAt, selectAt + 2800);
    assert.match(selectChunk, /if \(view === VIEW_SUIVRE\) \{/);
    assert.match(selectChunk, /leaveCinema\(\)/);
    assert.match(selectChunk, /setSidebarOpen\(true\)/);
    assert.match(selectChunk, /setToolsOpen\(true\)/);
  });

  it("utilise les PNG validés et le favicon d’origine", () => {
    const sidebar = read("../components/Sidebar.jsx");
    const index = read("../../index.html");
    assert.match(sidebar, /const NAVIGUIDE_LOGO = "\/logo-naviguide\.png"/);
    assert.match(sidebar, /const BERRY_LOGO = "\/logo-berry-mappemonde\.png"/);
    assert.match(index, /href="\/favicon-n-bl\.png"/);
    assert.ok(existsSync(join(src, "../../public/logo-naviguide.png")));
    assert.ok(existsSync(join(src, "../../public/logo-berry-mappemonde.png")));
    assert.ok(existsSync(join(src, "../../public/favicon-n-bl.png")));
  });

  it("réserve les contrôles de lecture à Tracer et à Suivre × ma route", () => {
    const app = read("../App.jsx");
    const filmBar = read("../components/SimulationFilmBar.jsx");
    const sidebar = read("../components/Sidebar.jsx");
    const simulationPanel = read("../components/EtapePanel.jsx");
    // Play / vitesses vivent aussi en Suivre sur ma route — jamais en
    // Suivre × Berry (le live officiel commande).
    assert.match(app, /const playControlsActive = isTracer \|\| suivreCustom;/);
    assert.match(app, /showPlaybackControls=\{playControlsActive\}/);
    assert.match(app, /if \(!playControlsActive\) return;/);
    assert.match(filmBar, /disabled=\{!showPlaybackControls\}/);
    assert.match(filmBar, /goToNextStop/);
    assert.doesNotMatch(sidebar, /onNext=\{handleSimNext\}/);
    assert.doesNotMatch(simulationPanel, /PrevNextButtons/);
  });

  it("entre en Suivre directement en LIVE cinéma", () => {
    const app = read("../App.jsx");
    assert.match(app, /if \(next === VIEW_SUIVRE\)/);
    assert.match(app, /setUserPreview\(false\)/);
    assert.match(app, /setCinemaMode\(true\)/);
    assert.match(app, /recaptureBoat\(\)/);
  });

  it("garde Saint-Maur en interne, sans choix de départ visible", () => {
    const app = read("../App.jsx");
    const departure = read("../components/DepartureField.jsx");
    assert.match(app, /voyage\.setStartAt\("saint-maur"\)/);
    assert.doesNotMatch(departure, /type="radio"/);
  });

  it("compacte le départ en format français avec une heure éditable", () => {
    const departure = read("../components/DepartureField.jsx");
    assert.match(departure, /naviguide-departure-field h-\[46px\]/);
    assert.match(departure, /formatDepartureDate/);
    assert.match(departure, /parseFrenchDepartureDate/);
    assert.match(departure, /placeholder="HH:MM"/);
    assert.doesNotMatch(departure, /type="date"/);
  });

  it("garde LIVE une seule fois dans le HUD et la météo sur la même ligne", () => {
    const app = read("../App.jsx");
    const filmBar = read("../components/SimulationFilmBar.jsx");
    const simulationPanel = read("../components/EtapePanel.jsx");
    assert.match(app, /liveStatus=\{isSuivre/);
    assert.match(filmBar, /<span data-testid="weather-line" className="text-cyan-200\/85">/);
    assert.doesNotMatch(simulationPanel, /bg-emerald-500\/20/);
  });

  it("dégage le zoom Leaflet et aligne les deux chevrons", () => {
    const sidebar = read("../components/Sidebar.jsx");
    const tools = read("../components/ToolsSidebar.jsx");
    assert.match(sidebar, /naviguide-sidebar-toggle--left[\s\S]{0,80}absolute top-4/);
    assert.doesNotMatch(sidebar, /top-\[92px\]/);
    assert.match(tools, /naviguide-sidebar-toggle--right[\s\S]{0,40}absolute top-4/);
    assert.match(tools, /w-9 h-9/);
    assert.doesNotMatch(tools, /w-12 h-12/);
  });

  it("retire la mention non éditable et la date répétée de la jambe", () => {
    const app = read("../App.jsx");
    const panel = read("../components/EtapePanel.jsx");
    const fr = read("../i18n/fr.js");
    assert.doesNotMatch(app, /civilDate=/);
    assert.doesNotMatch(panel, /civilDate/);
    assert.doesNotMatch(fr, /non éditable/);
  });

  it("n’affiche un titre de briefing que si briefing_title est fourni", () => {
    const sidebar = read("../components/Sidebar.jsx");
    assert.match(sidebar, /plan\?\.briefing_title/);
    assert.doesNotMatch(sidebar, /t\("briefing"\)/);
  });

  it("Un seul encadré, aucune carte flottante hors film", () => {
    const sidebar = read("../components/Sidebar.jsx");
    const app = read("../App.jsx");
    const ici = read("../components/IciMaintenant.jsx");
    assert.match(sidebar, /<IciMaintenant/);
    assert.match(sidebar, /<LogbookChat/);
    assert.doesNotMatch(sidebar, /<MomentNowCard /);
    assert.doesNotMatch(sidebar, /<FreeMomentBlock /);
    assert.doesNotMatch(app, /<MomentNowCard/);
    assert.doesNotMatch(app, /<FreeMomentBlock/);
    assert.match(app, /stop=\{replay\.active \? null : escaleStop\}/);
    assert.match(ici, /<EscaleSheet/);
    assert.doesNotMatch(ici, /ListenButton/);
  });

  it("Date de départ dans le panneau droit, revue dans l'encadré gauche, replay distinct, horloge avec année", () => {
    const app = read("../App.jsx");
    const tools = read("../components/ToolsSidebar.jsx");
    const ici = read("../components/IciMaintenant.jsx");
    const bar = read("../components/SimulationFilmBar.jsx");
    const clock = read("../engine/voyageClock.js");
    const depAt = tools.indexOf("{showDeparture ?");
    assert.ok(depAt >= 0, "Date de départ toujours dans le panneau droit");
    assert.doesNotMatch(tools, /<PlanReview/);
    assert.doesNotMatch(tools, /planReview && !drawing/);
    assert.match(ici, /<PlanReview/);
    // L'horloge officielle ne porte que Suivre × Berry ; ma route lit
    // le voyage serveur perso (voyage.clock) dans les deux modes.
    assert.match(app, /suivreBerry \? \(official\.clock \|\| voyage\.clock\) : voyage\.clock/);
    assert.match(app, /const \[replayT0, setReplayT0\] = useState\(DEFAULT_T0_ISO\)/);
    assert.match(app, /t0: suivreBerry \? replayT0/);
    assert.match(app, /followClockLineFromT0/);
    assert.match(app, /t0: suivreBerry \? replayT0/);
    assert.match(app, /showDeparture=\{isSuivre\}/);
    assert.match(app, /departureT0=\{suivreBerry \? replayT0 : voyage\.t0\}/);
    assert.match(app, /onDepartureT0=\{suivreBerry \? setReplayT0 : voyage\.setT0\}/);
    assert.match(bar, /data-testid="replay-departure"/);
    assert.match(bar, /<DepartureField/);
    assert.match(clock, /getUTCFullYear\(\)/);
    assert.match(clock, / · \$\{hh\}:\$\{mm\} UTC/);
  });

  it("Panneau droit Tracer replie Polaires, déplie Calques, Demander conseil reste", () => {
    const app = read("../App.jsx");
    const tools = read("../components/ToolsSidebar.jsx");
    const skipper = read("../components/SkipperOrdersPanel.jsx");
    const sim = read("../components/EtapePanel.jsx");
    assert.match(app, /tracerLayout=\{!isSuivre\}/);
    assert.doesNotMatch(app, /showAdvice=/);
    assert.match(tools, /tracerLayout = false/);
    assert.match(tools, /function FoldDetails/);
    assert.match(tools, /function LayersDrawer/);
    assert.match(tools, /data-testid="layers-drawer"/);
    assert.match(tools, /readSessionOpen\(layersFoldKey\(tracerLayout\), Boolean\(tracerLayout\)\)/);
    assert.doesNotMatch(tools, /open=\{polarOpen\}/);
    assert.doesNotMatch(tools, /open=\{layersOpen\}/);
    assert.doesNotMatch(tools, /data-testid="ask-advice"/);
    assert.match(sim, /data-testid="ask-advice"/);
    assert.match(skipper, /data-testid="skipper-orders"/);
    assert.doesNotMatch(skipper, /<details open/);
    assert.match(tools, /data-testid="polar-box"/);
    assert.match(tools, /data-testid="export-box"/);
  });

  it("Barre film et contexte du chat lisent la même source", () => {
    const app = read("../App.jsx");
    const bar = read("../components/SimulationFilmBar.jsx");
    assert.match(app, /const displayKnots = isSuivre/);
    assert.match(app, /boatKnots=\{displayKnots\}/);
    assert.match(app, /speedKnots: Number\.isFinite\(displayKnots\) \? displayKnots : null/);
    assert.match(app, /follow: isSuivre/);
    assert.match(app, /window\.__naviguideDebug/);
    assert.match(bar, /data-testid="regime-legend"/);
    assert.match(bar, /data-testid="speed-regime-pill"/);
    assert.match(bar, /data-testid="prev-stop"/);
    assert.doesNotMatch(app, /boatKnots=\{expeditionSpeed\.knots\}/);
    assert.doesNotMatch(app, /chatMeasuredKnots = atQuay \? 0 : expeditionSpeed\.knots/);
  });
});
