// La couche route dessine la source courante et seulement elle,
// passé ET à venir, dans les deux modes. Ce test rejoue la séquence de la
// revue du porteur (B2/B3) : hard refresh → Tracer → Tracer votre propre
// route → La Rochelle → Caraïbes → Terminer → Suivre.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { routeDrawPlan } from "./routeDrawPlan.js";
import { resolveRouteSource, routeForSource } from "../utils/routeSource.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (file) => readFileSync(join(here, file), "utf8");

const drawn = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "LineString", coordinates: [[-1.5, 46.1], [-61.0, 15.3]] }, properties: {} },
    { type: "Feature", geometry: { type: "Point", coordinates: [-1.5, 46.1] }, properties: { name: "La Rochelle" } },
  ],
};

/** Le câblage App → scène : la scène reçoit routeForView, jamais le brut. */
function sceneInput(state, { drawingMode = false, sceneReady = true } = {}) {
  const source = resolveRouteSource(state.routeKind, state.customRoute);
  return {
    sceneReady,
    drawingMode,
    customRoute: routeForSource(source, state.customRoute),
  };
}

describe("routeDrawPlan — une seule route à l'écran", () => {
  it("rejoue la séquence Tracer → Terminer → Suivre : ma route, seule, dans les deux modes", () => {
    const state = { routeKind: "berry", customRoute: null };

    // Hard refresh (Suivre × Berry) : la route Berry, passé ET à venir.
    assert.deepEqual(routeDrawPlan(sceneInput(state)), { visible: true, kind: "berry" });

    // Tracer (vue Simulation) sans route perso : toujours Berry.
    assert.deepEqual(routeDrawPlan(sceneInput(state)), { visible: true, kind: "berry" });

    // Tracer votre propre route : seul le tracé en cours se dessine.
    assert.deepEqual(routeDrawPlan(sceneInput(state, { drawingMode: true })), { visible: true, kind: "drawing" });

    // Terminer : routeKind = custom (handleCustomRoute) — Tracer dessine ma route, seule.
    state.routeKind = "custom";
    state.customRoute = drawn;
    assert.deepEqual(routeDrawPlan(sceneInput(state)), { visible: true, kind: "custom" });

    // Suivre : l'état (routeKind, customRoute) ne bouge pas — ma route, seule,
    // jamais « custom + Berry parcourue » (B2) ni « Berry sans l'à-venir » (B3).
    assert.deepEqual(routeDrawPlan(sceneInput(state)), { visible: true, kind: "custom" });

    // Pilule Berry-Mappemonde : retour à la route Berry, seule.
    state.routeKind = "berry";
    state.customRoute = null;
    assert.deepEqual(routeDrawPlan(sceneInput(state)), { visible: true, kind: "berry" });
  });

  it("rien n'est dessiné tant que la scène n'est pas prête (hors tracé)", () => {
    assert.deepEqual(routeDrawPlan({ sceneReady: false, drawingMode: false, customRoute: drawn }), { visible: false, kind: null });
  });

  it("le contrôleur suit le plan : custom OU Berry, jamais les deux", () => {
    const src = read("./MapSceneController.js");
    const start = src.indexOf("  syncRoute()");
    const end = src.indexOf("  syncAltRoute()");
    assert.ok(start >= 0 && end > start, "syncRoute introuvable");
    const chunk = src.slice(start, end);
    assert.match(chunk, /routeDrawPlan\(input\)/);
    // La branche custom rend la main AVANT les segments Berry : une route à la fois.
    assert.match(chunk, /plan\.kind === "custom"\) \{[\s\S]*?return;\s*\}\s*\(input\.segments \|\| \[\]\)\.forEach/);
    // La branche Berry garde la route à venir : segments + sauts aériens (jump).
    assert.match(chunk, /officialAirRouteStyles\(segment\)/);
    assert.match(chunk, /pts\[i \+ 1\]\.jump/);
  });

  it("App nourrit la scène avec routeForView — plus de « Suivre force Berry »", () => {
    const app = read("../App.jsx");
    assert.doesNotMatch(app, /isSuivre \? null : customRoute/);
    assert.match(app, /const routeSource = resolveRouteSource\(routeKind, customRoute\);/);
    assert.match(app, /customRoute: routeForView,/);
    // Les stats et l'export décrivent la même route que la scène.
    assert.match(app, /routeForView \? featuresToSegments\(routeForView\) : segments/);
  });

  it("Suivre × ma route : horloge du voyage perso, jamais /voyage/official", () => {
    const app = read("../App.jsx");
    // L'horloge officielle (PUT/GET /voyage/official) ne sert que Suivre × Berry.
    assert.match(app, /const official = useOfficialExpedition\(\{\s*enabled: suivreBerry,/);
    assert.match(app, /enabled: Boolean\(suivreBerry && officialClock\)/);
    assert.match(app, /useOfficialJournal\(\{ enabled: suivreBerry \}\)/);
    // Le voyage serveur de la route perso porte Suivre × custom comme Tracer.
    assert.match(app, /enabled: \(isTracer \|\| suivreCustom\) && routeReady,/);
    assert.match(app, /follow: suivreCustom,/);
    assert.match(app, /const officialClock = suivreBerry \? \(official\.clock \|\| voyage\.clock\) : voyage\.clock;/);
    // La position live vient de la source : vessel.live pour ma route.
    assert.match(app, /const sourceLive = suivreCustom \? \(vessel\.live \|\| customClientLive\) : official\.live;/);
    // Revoir sur ma route — même bouton, actif quand le film perso est ready.
    assert.doesNotMatch(app, /unavailable: true/);
    assert.match(app, /enabled: isSuivre && \(suivreBerry \|\| Boolean\(customVoyageId\)\)/);
    assert.match(app, /voyageId: suivreCustom \? customVoyageId : "official"/);
    const bar = read("../components/SimulationFilmBar.jsx");
    assert.match(bar, /replayPreparing/);
    assert.match(bar, /data-testid="replay-start"/);
  });
});
