import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(join(root, rel), "utf8");

describe("recette A–G (contrats source)", () => {
  it("A — bateau et drapeaux sur la même lon enveloppée que la caméra", () => {
    const scene = read("../map/MapSceneController.js");
    assert.match(scene, /stabilizeWorldLng/);
    assert.match(scene, /shouldResnapCamera/);
    assert.match(scene, /cameraLngForBoat/);
    assert.match(scene, /worldCopyJump:\s*false/);
  });

  it("C — plus d’ArrivalCard ni d’effect banner", () => {
    const app = read("../App.jsx");
    assert.doesNotMatch(app, /ArrivalCard/);
    assert.doesNotMatch(app, /arrivalBanner/);
    assert.doesNotMatch(app, /setArrivalBanner/);
  });

  it("D — KeyC ignore meta/ctrl", () => {
    const app = read("../App.jsx");
    assert.match(app, /isCinemaKey/);
    assert.match(read("./cinemaHotkey.js"), /metaKey \|\| e\.ctrlKey/);
  });

  it("E — GRIB2 branché, même lon enveloppée que le bateau", () => {
    assert.match(read("../map/MapScene.jsx"), /maritimeLayers\.showGrib && scene\.isSuivre/);
    assert.match(read("../layers/useToggleLayers.js"), /DEFAULT_SHOW_GRIB/);
    const grib = read("../layers/useGribCorridorLayer.js");
    assert.match(grib, /markerWorldLngs/);
    assert.match(grib, /cameraLngForBoat/);
    assert.match(grib, /getPane\("grib"\)/);
    assert.doesNotMatch(grib, /getPane\("boat"\)/);
    assert.match(read("../layers/layerOrder.js"), /name:\s*"grib"/);
    const official = read("../hooks/useOfficialExpedition.js");
    assert.match(official, /officialGribQuery\(serverClock/);
    assert.doesNotMatch(official, /sampleClockAtTime\(clockRef/);
    assert.match(read("../hooks/gribStatus.js"), /wrapLon\(sample\.lon\)/);
    assert.match(read("../main.jsx"), /Icon\.Default\.mergeOptions/);
    assert.match(read("./getCardinalDirection.js"), /typeof input === "number"/);
  });

  it("F — Annuler Draw + bateau après 1er segment", () => {
    const app = read("../App.jsx");
    assert.match(app, /handleDrawCancel/);
    assert.match(read("../map/MapSceneController.js"), /drawnSegments\?\.length >= 1/);
    assert.match(read("../components/Sidebar.jsx"), /onDrawCancel/);
  });

  it("G — Open-Meteo une fois, jambe sans modèle", () => {
    const panel = read("../components/EtapePanel.jsx");
    assert.doesNotMatch(panel, /forecastModel/);
    assert.doesNotMatch(panel, /clockSample\.model/);
    assert.doesNotMatch(panel, /Open-Meteo/);
    assert.match(read("../App.jsx"), /buildWeatherLine\(/);
    assert.match(read("../components/SimulationFilmBar.jsx"), /weather-line/);
  });

  it("H — GRIB sous le bateau, catamaran SVG proue = cap", () => {
    const icon = read("../engine/catamaranIcon.js");
    const marker = read("../map/MapSceneController.js");
    assert.match(icon, /data-bow="north"/);
    assert.match(icon, /data-marker-rotatable/);
    assert.match(marker, /catamaranSvg/);
    assert.match(marker, /applyMarkerRotation/);
    assert.match(marker, /planeHtml/);
    assert.doesNotMatch(marker, /catamaran\.jpg/);
    assert.doesNotMatch(icon, /scaleX/);
  });

  it("I — atlas climatologie peint + moteur, distinct du GRIB2", () => {
    const app = read("../App.jsx");
    assert.match(read("../map/MapScene.jsx"), /useClimatologyLayer/);
    assert.match(app, /useAtlasLookup/);
    assert.match(app, /climatology-banner/);
    assert.doesNotMatch(app, /overlay climatologie à l’étape 6/);
    assert.match(read("../layers/useToggleLayers.js"), /showClimoWind/);
    assert.match(read("../layers/useToggleLayers.js"), /showClimoWave/);
    assert.match(read("../layers/useToggleLayers.js"), /showClimoCurrent/);
    assert.match(read("../layers/useToggleLayers.js"), /showClimoCyclones/);
    assert.match(read("../layers/useClimatologyLayer.js"), /waveP50/);
    assert.match(read("../layers/useClimatologyLayer.js"), /waveP90/);
    assert.match(read("../layers/useClimatologyLayer.js"), /wave-mean/);
    assert.match(read("../layers/useClimatologyLayer.js"), /cyclones/);
    assert.match(read("../layers/useClimatologyLayer.js"), /climoPointLngs/);
    assert.match(read("../layers/useClimatologyLayer.js"), /cycloneLatLngCopies/);
    assert.match(read("../layers/useClimatologyLayer.js"), /groupCycloneFeatures/);
    assert.match(read("../layers/climatologyWorld.js"), /unwrapCycloneCoords/);
    assert.doesNotMatch(read("../layers/climatologyWorld.js"), /splitCycloneAtMeridian/);
    assert.match(read("./fixtures/climatology-bi/cycloneTracks.js"), /unwrapCycloneCoords/);
    assert.doesNotMatch(read("./fixtures/climatology-bi/cycloneTracks.js"), /splitCycloneAtMeridian/);
    assert.match(read("./fixtures/climatology-bi/useClimatologyLayer.js"), /cycloneLatLngCopies/);
    assert.match(read("./fixtures/climatology-bi/useClimatologyLayer.js"), /groupCycloneFeatures/);
    assert.match(read("../layers/layerOrder.js"), /climatology-raster/);
    assert.match(read("../utils/atlasPoint.js"), /kind !== "climatology"/);
    assert.match(read("../engine/voyageClock.js"), /windAt/);
    assert.match(read("../engine/ici.js"), /climatology: null/);
    assert.match(read("../engine/iciBriefing.js"), /Climatologie de \$\{when\} \(atlas Copernicus Marine/); // climatology named as such, never as a forecast
    assert.match(read("../hooks/useIciDossier.js"), /dest_lat/);
    assert.match(read("../hooks/useIciDossier.js"), /detectEvents/);
    assert.match(read("../hooks/useIciDossier.js"), /judgeEvents/);
    assert.match(read("../hooks/useIciDossier.js"), /No chat, no Tavily/);
    assert.match(read("../hooks/useIciDossier.js"), /enqueueStory/);
    assert.doesNotMatch(read("../hooks/useIciDossier.js"), /await enqueueStory|await narrate|Nemotron/);
    assert.match(read("../engine/eventRules.js"), /WIND_SHIFT_KT = 8/);
    assert.match(read("../engine/displayJudge.js"), /hide \| now \| later \| group/);
    assert.match(read("../engine/iciAlong.js"), /sampleLeg/);
    assert.match(read("../hooks/useIciAlong.js"), /thin: "1"/);
    assert.match(read("../components/SimulationFilmBar.jsx"), /event-pill-/);
    assert.match(read("../engine/storyQueue.js"), /nim-or-claude/);
    assert.doesNotMatch(read("../hooks/useIciAlong.js"), /Nemotron|Token Factory|enqueueStory/);
    assert.doesNotMatch(read("../hooks/useIciDossier.js"), /Nemotron|Token Factory|Tavily\?/);
    assert.match(read("../engine/storyQueue.js"), /Not Nemotron/);
    assert.doesNotMatch(read("../engine/storyQueue.js"), /tavily\.search|nvidia-nemotron/);
    assert.match(read("../engine/storyQueue.js"), /void runStory/);
    assert.doesNotMatch(read("../utils/sceneGate.js"), /detectEvents|zee-enter/);
    const grib = read("../layers/useGribCorridorLayer.js");
    assert.match(grib, /status !== "ready"/);
    assert.doesNotMatch(grib, /climatology\/point/);
  });
});
