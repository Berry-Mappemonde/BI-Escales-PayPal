import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const hook = readFileSync(join(here, "useSkipperOrders.js"), "utf8");
const panel = readFileSync(join(here, "..", "components", "SkipperOrdersPanel.jsx"), "utf8");
const tools = readFileSync(join(here, "..", "components", "ToolsSidebar.jsx"), "utf8");
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");

describe("useSkipperOrders contract", () => {
  it("persists the orders in this tab (same v1 key), sanitized, and never awaits a model", () => {
    assert.match(hook, /readSavedOrders\(storage\(\)\)/);
    assert.match(hook, /writeSavedOrders\(storage\(\), next\)/);
    assert.match(hook, /sanitizeSaved\(\{ \.\.\.prev, \.\.\.patch \}\)/);
    assert.match(hook, /clearSavedOrders\(storage\(\)\)/);
    // The wind of the moment enters the orders (planning speed = polar × wind), rounded so they only move when the polar would.
    assert.match(hook, /resolveOrders\(saved, \{ polar, mode, wind: w \}\)/);
    assert.match(hook, /export function roundedWind/);
    assert.match(hook, /NOTICE_MS = 6000/);
    assert.match(hook, /Never awaits a model/);
    assert.match(hook, /Never rewinds the film/);
    assert.doesNotMatch(hook, /fetch\(|await |Nemotron|Tavily|mongo/i);
  });

  it("exposes S6 / S7 setters and shows the cyan line on profile / comfort / horizon, not per Expert keystroke", () => {
    assert.match(hook, /setComfort/);
    assert.match(hook, /setHorizon/);
    assert.match(hook, /setExpert = useCallback\(\(id, value\)/);
    assert.match(hook, /clampExpert\(id, value\)/);
    assert.match(hook, /function noticeKey\(saved\)/);
    assert.match(hook, /\$\{saved\.profile\}\|\$\{saved\.comfort \|\| "normal"\}\|\$\{saved\.horizonH \|\| ""\}/);
  });

  it("proposes coastal for a small polar and lets the skipper refuse", () => {
    assert.match(hook, /acceptSuggest/);
    assert.match(hook, /dismissSuggest/);
    assert.match(hook, /never switches silently/);
  });
});

describe("SkipperOrdersPanel contract (revue du 19 sept. : « Paramètres avancés » repliés)", () => {
  it("is one folded <details> named Paramètres avancés; the boat block comes first, with typed L / draft / gale", () => {
    assert.match(panel, /<details className="px-4 py-3 border-t[^>]*data-testid="skipper-orders"/);
    assert.match(panel, /t\("advancedSettings"\)/);
    assert.doesNotMatch(panel, /<details open/);
    const boatAt = panel.indexOf('data-testid="skipper-boat"');
    const profileAt = panel.indexOf("items={PROFILES}");
    const comfortAt = panel.indexOf('data-testid="skipper-comfort"');
    const expertAt = panel.indexOf('data-testid="skipper-expert"');
    assert.ok(boatAt > 0 && boatAt < profileAt && profileAt < comfortAt && comfortAt < expertAt, "boat → character → comfort → Chiffres");
    const boatBlock = panel.slice(boatAt, profileAt);
    assert.doesNotMatch(boatBlock, /label=\{t\("skipperBoat"\)\}/);
    assert.match(tools, /data-testid="polar-boat"/);
    assert.match(boatBlock, /id="loaM"/);
    assert.match(boatBlock, /id="draftM"/);
    assert.match(boatBlock, /BOAT_EXPERT_IDS\.map/); // galeKt / galeHoldKt, editable, Beaufort as default
    assert.match(boatBlock, /skipperPlanningKn/);
    assert.match(panel, /onBoat/);
    assert.doesNotMatch(panel, /skipperSharedClock|exampleLine|skipperRainSimulation/);
    assert.doesNotMatch(panel, /wind-gale|hs-shift|depth-alert/);
  });

  it("S6: comfort pills with the live effect, horizon pills greyed in Simulation", () => {
    assert.match(panel, /items=\{COMFORTS\}/);
    assert.match(panel, /data-testid="skipper-comfort-effect"/);
    assert.match(panel, /skipperComfortAria/);
    assert.match(panel, /items=\{HORIZONS_H\}/);
    assert.match(panel, /disabled=\{!isSuivre\}/);
    assert.match(panel, /skipperHorizonLeg/);
  });

  it("S7: « Chiffres » stays a folded drawer at the bottom, numbers only, back-to-profile arrow", () => {
    const drawer = panel.slice(panel.indexOf('data-testid="skipper-expert"'), panel.lastIndexOf("</details>"));
    assert.ok(drawer.length > 0, "details drawer exists");
    assert.match(drawer, /skipperExpertTitle/);
    assert.match(drawer, /NUMBER_EXPERT_IDS\.map/);
    assert.match(panel, /type="number"/);
    assert.match(panel, /min=\{field\.min\}[^]*max=\{field\.max\}[^]*step=\{field\.step\}/);
    assert.match(panel, /onChange\?\.\(id, null\)/);
  });

  it("is mounted in the tools sidebar after the polar box, not on the film bar", () => {
    assert.match(tools, /<SkipperOrdersPanel/);
    const polarBox = tools.indexOf('data-testid="polar-box"');
    const panelAt = tools.indexOf("<SkipperOrdersPanel");
    assert.ok(polarBox > 0 && panelAt > polarBox, "panel sits after the polar box");
    assert.match(tools, /onBoat=\{onSkipperBoat\}/);
    const filmBar = readFileSync(join(here, "..", "components", "SimulationFilmBar.jsx"), "utf8");
    assert.doesNotMatch(filmBar, /SkipperOrders|skipperProfile/);
  });

  it("App passes the same orders to detectors, judge and lookahead, and the cyan notice to the briefing", () => {
    assert.match(app, /useSkipperOrders\(\{/);
    assert.equal((app.match(/orders: skipper\.orders/g) || []).length, 2);
    assert.match(app, /skipperNotice=\{skipper\.notice\}/);
    assert.match(app, /skipperOrders=\{skipper\.orders\}/);
    assert.match(app, /onSkipperComfort=\{skipper\.setComfort\}/);
    assert.match(app, /onSkipperHorizon=\{skipper\.setHorizon\}/);
    assert.match(app, /onSkipperExpert=\{skipper\.setExpert\}/);
    assert.match(tools, /onComfort=\{onSkipperComfort\}/);
    assert.match(tools, /onExpert=\{onSkipperExpert\}/);
    const dossier = readFileSync(join(here, "useIciDossier.js"), "utf8");
    assert.match(dossier, /q\.set\("radius_nm", String\(radiusNm\)\)/);
    assert.match(dossier, /radiusNm: radiusRef\.current/);
    assert.match(dossier, /radiusRef\.current = /);
    assert.doesNotMatch(app, /knots: expeditionSpeed\.knots,\n\s*\}\);\n\n\s*const iciPack/);
  });
});
