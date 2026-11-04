import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "url";
import { describe, it } from "node:test";
import { canFinishDrawnRoute, drawingRefusalPhrase, importPointsSequential, loadLeg } from "./useRouteDrawing.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const here = dirname(fileURLToPath(import.meta.url));
const hook = readFileSync(join(here, "useRouteDrawing.js"), "utf8");

const PTS = [
  { lat: 46.157, lon: -1.151, name: "La Rochelle" },
  { lat: 43.545, lon: -5.662, name: "Gijon" },
  { lat: 38.722, lon: -9.139, name: "Lisbonne" },
];

function makeSession() {
  const points = [];
  const segments = [];
  let resets = 0;
  async function addPoint(lat, lon, extra) {
    const next = { lat, lon, ...(extra?.name ? { name: extra.name } : {}) };
    const prev = points.at(-1);
    points.push(next);
    if (prev) segments.push({ from: prev, to: next });
  }
  function reset() {
    resets += 1;
    points.length = 0;
    segments.length = 0;
  }
  return { points, segments, resets: () => resets, addPoint, reset };
}

describe("useRouteDrawing importPoints", () => {
  it("expose importPoints qui rejoue importPointsSequential (reset + un addPoint par waypoint)", () => {
    assert.match(hook, /export async function importPointsSequential/);
    assert.match(hook, /const importPoints = useCallback/);
    assert.match(hook, /importPointsSequential\(addPoint, reset, points\)/);
    assert.match(hook, /if \(updated\.length >= 2\) return fetchSegment/);
    assert.match(hook, /importPoints,/);
  });

  it("importPoints ≡ N clics sur une route vide", async () => {
    const clicks = makeSession();
    for (const p of PTS) await clicks.addPoint(p.lat, p.lon, { name: p.name });

    const imported = makeSession();
    await importPointsSequential(imported.addPoint, imported.reset, PTS);

    assert.equal(imported.resets(), 1);
    assert.deepEqual(imported.points, clicks.points);
    assert.deepEqual(imported.segments, clicks.segments);
    assert.equal(imported.segments.length, 2);
  });

  it("remplace la route en cours (reset avant les N clics)", async () => {
    const session = makeSession();
    await session.addPoint(0, 0, { name: "Ancien" });
    await importPointsSequential(session.addPoint, session.reset, PTS);
    assert.equal(session.resets(), 1);
    assert.equal(session.points.length, 3);
    assert.equal(session.points[0].name, "La Rochelle");
    assert.equal(session.points.some((p) => p.name === "Ancien"), false);
  });
});

describe("brouillon DM6 — reset seulement à l'abandon", () => {
  it("handleDrawStart ne vide plus le brouillon ; Annuler et supprimer le font", () => {
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    const startAt = app.indexOf("const handleDrawStart = ");
    const cancelAt = app.indexOf("const handleDrawCancel = ");
    const finishAt = app.indexOf("const handleDrawFinish = ");
    const deleteAt = app.indexOf("const handleCustomDelete = ");
    assert.ok(startAt >= 0 && cancelAt > startAt && finishAt > cancelAt && deleteAt > finishAt);
    assert.doesNotMatch(app.slice(startAt, cancelAt), /resetDrawState\(\)/);
    assert.match(app.slice(cancelAt, finishAt), /resetDrawState\(\)/);
    assert.match(app.slice(deleteAt, deleteAt + 400), /resetDrawState\(\)/);
    assert.match(app, /endDrawingWorld/);
    assert.match(app, /armDrawingWorldRef/);
    const berryAt = app.indexOf("const handleRouteSwitchToBerry");
    assert.ok(berryAt >= 0);
    assert.match(app.slice(berryAt, berryAt + 700), /drawingModeRef\.current|parkDrawing\(\)/);
    assert.doesNotMatch(app.slice(berryAt, berryAt + 700), /_resetDrawState\(\)/);
  });
});

describe("↶ pendant le calcul d'une jambe", () => {
  const undoAt = hook.indexOf("const undo = useCallback(");
  const redoAt = hook.indexOf("const redo = useCallback(");
  const undoBody = hook.slice(undoAt, redoAt);

  it("n'invalide que la jambe retirée, pas celles encore en calcul", () => {
    assert.ok(undoAt > 0 && redoAt > undoAt);
    assert.doesNotMatch(undoBody, /epochRef\.current \+= 1/);
    assert.match(undoBody, /slotGenRef\.current\[slot\]/);
    assert.match(hook, /pointsRef\.current\[slot \+ 1\] !== to/);
  });

  it("n'expose jamais de trou dans les jambes", () => {
    assert.doesNotMatch(hook, /setDrawnSegments\(\[\.\.\.segmentsRef\.current\]\)/);
    assert.match(hook, /setDrawnSegments\(denseSegments\(segmentsRef\.current\)\)/);
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.doesNotMatch(app, /drawnSegments\.some\(\(s\) => s\.failed\)/);
  });

  it("le masque de terre mort a disparu", () => {
    assert.doesNotMatch(hook, /loadedLandMask|__naviguideLandMask/);
  });
});

describe("plafond de points", () => {
  it("le texte FR et EN suit DRAW_MAX_POINTS", async () => {
    const { DRAW_MAX_POINTS } = await import("./useRouteDrawing.js");
    const { ROUTE_IMPORT_MAX_POINTS } = await import("../utils/routeImport.js");
    assert.equal(DRAW_MAX_POINTS, ROUTE_IMPORT_MAX_POINTS);
    for (const lang of ["fr", "en"]) {
      const src = readFileSync(join(here, "..", "i18n", `${lang}.js`), "utf8");
      assert.match(src, /drawPointLimit:\s*"\{max\} points maximum"/);
      assert.match(src, /importRouteTruncated:\s*"\{max\} points maximum"/);
    }
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.match(app, /t\("drawPointLimit", \{ max: DRAW_MAX_POINTS \}\)/);
    assert.match(app, /t\("importRouteTruncated", \{ max: DRAW_MAX_POINTS \}\)/);
  });
});

describe("loadLeg: never a straight line the server did not route", () => {
  const LA_ROCHELLE = { lat: 46.15, lon: -1.16 };
  const GULF_OF_LION = { lat: 43.0, lon: 4.0 };
  const withFetch = async (impl, run) => {
    const saved = globalThis.fetch;
    globalThis.fetch = impl;
    try { return await run(); } finally { globalThis.fetch = saved; }
  };
  const answer = (status, body) => async () => ({ status, ok: status >= 200 && status < 300, json: async () => body });

  // Exactly what the app calls (no land mask is passed or loaded).
  for (const [label, impl, error] of [
    ["500", answer(500, { detail: "boom" }), "server"],
    ["404", answer(404, { detail: "Not Found" }), "server"],
    ["200 without a line", answer(200, { type: "Feature", geometry: null }), "server"],
    ["non-JSON 502", async () => ({ status: 502, ok: false, json: async () => { throw new SyntaxError("html"); } }), "server"],
    ["network", async () => { throw new TypeError("Failed to fetch"); }, "network"],
  ]) {
    it(`${label}: no leg, no coordinates — an error to tell`, async () => {
      const leg = await withFetch(impl, () => loadLeg(LA_ROCHELLE, GULF_OF_LION));
      assert.deepEqual(leg, { error });
    });
  }

  it("a routed answer is still a leg", async () => {
    const line = { type: "Feature", geometry: { type: "LineString", coordinates: [[-1.16, 46.15], [-9.5, 43], [4, 43]] }, properties: { length: 2000, units: "km" } };
    const leg = await withFetch(answer(200, line), () => loadLeg(LA_ROCHELLE, GULF_OF_LION));
    assert.equal(leg.coords.length, 3);
    assert.ok(Math.abs(leg.nm - 2000 / 1.852) < 1e-6);
    assert.equal("failed" in leg, false);
  });

  it("503, 422 on_land and crosses_land keep their meaning", async () => {
    assert.deepEqual(await withFetch(answer(503, { detail: "busy" }), () => loadLeg(LA_ROCHELLE, GULF_OF_LION)), { busy: true });
    assert.deepEqual(await withFetch(answer(422, { detail: "crosses_land" }), () => loadLeg(LA_ROCHELLE, GULF_OF_LION)), { reject: "crosses_land", end: "end" });
    assert.deepEqual(await withFetch(answer(422, { detail: "on_land", end: "on_land_start" }), () => loadLeg(LA_ROCHELLE, GULF_OF_LION)), { reject: "on_land", end: "start" });
  });

  it("the hook keeps the point without a leg and says why (no fallback line anywhere)", () => {
    assert.doesNotMatch(hook, /rhumbCoords|refuseRhumbFallback|failed:/);
    const body = hook.slice(hook.indexOf("const loadSegment"), hook.indexOf("const fetchSegment ="));
    const onError = body.slice(body.indexOf("if (result?.error)"), body.indexOf("if (result?.reject)"));
    assert.match(onError, /notify\(result\.error === "network" \? "network_error" : "server_error"\)/);
    assert.match(onError, /return;/);
    assert.doesNotMatch(onError, /segmentsRef\.current\s*=/);
  });

  it("un 422 terre ou traversée s'écrit dans le cadre, Terminer reste grisé", async () => {
    const tFr = (key) => fr[key];
    const tEn = (key) => en[key];
    const land = await withFetch(
      answer(422, { detail: "on_land", end: "on_land_end" }),
      () => loadLeg(LA_ROCHELLE, GULF_OF_LION),
    );
    const cross = await withFetch(
      answer(422, { detail: "crosses_land" }),
      () => loadLeg(LA_ROCHELLE, GULF_OF_LION),
    );
    assert.equal(land.reject, "on_land");
    assert.equal(cross.reject, "crosses_land");
    assert.equal(drawingRefusalPhrase(land.reject, tFr), "Point sur terre : non ajouté");
    assert.equal(drawingRefusalPhrase(cross.reject, tFr), "La ligne droite traverse la terre");
    assert.equal(drawingRefusalPhrase(land.reject, tEn), "Point on land: not added");
    assert.equal(drawingRefusalPhrase(cross.reject, tEn), "Straight line crosses land");
    assert.equal(canFinishDrawnRoute(2, 0, false, "on_land"), false);
    assert.equal(canFinishDrawnRoute(1, 0, false, "crosses_land"), false);
    assert.equal(canFinishDrawnRoute(2, 1, true, "on_land"), false);
    const refuse = hook.slice(hook.indexOf("if (result?.reject)"), hook.indexOf("const next = segmentsRef"));
    assert.match(refuse, /removePointAt/);
    assert.match(refuse, /notify\(result\.reject\)/);
    const tools = readFileSync(join(here, "..", "components", "ToolsSidebar.jsx"), "utf8");
    const box = tools.slice(tools.indexOf("function DrawingBox"), tools.indexOf("function ExpeditionBox"));
    assert.match(box, /drawingRefusalPhrase\(drawing\?\.notice, t\)/);
    assert.match(box, /\{refusal \?/);
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.match(app, /notice: drawingNotice\?\.code \|\| null/);
    assert.match(app, /canFinishDrawnRoute\(drawnPoints\.length, drawnSegments\.length, drawingLoading, drawingNotice\?\.code\)/);
  });

  it("une paire en mer, Australie vers Californie, active Terminer", async () => {
    const australia = { lat: -18.2, lon: 153.8 };
    const california = { lat: 34.5, lon: -123.5 };
    const line = {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [[153.8, -18.2], [-140, 20], [-123.5, 34.5]],
      },
      properties: { length: 12000, units: "km" },
    };
    const leg = await withFetch(answer(200, line), () => loadLeg(australia, california));
    assert.equal(leg.coords.length, 3);
    assert.ok(leg.nm > 1000);
    assert.equal("reject" in leg, false);
    assert.equal(canFinishDrawnRoute(2, 1, false, null), true);
    assert.equal(canFinishDrawnRoute(2, 1, false, undefined), true);
    assert.equal(drawingRefusalPhrase(null, (key) => fr[key]), "");
  });
});
