import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import { displayStopName } from "../utils/stopLabels.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "EscaleLegend.jsx"), "utf8");
const tools = readFileSync(join(here, "ToolsSidebar.jsx"), "utf8");

describe("EscaleLegend — plus de carré vert", () => {
  it("ne rend plus escale-sheet-open", () => {
    assert.doesNotMatch(src, /escale-sheet-open/);
    assert.doesNotMatch(src, /▤/);
    assert.doesNotMatch(src, /onSheet/);
    assert.match(src, /data-testid="escale-legend"/);
  });
});

describe("EscaleLegend — informative dans tous les modes (étend RE2)", () => {
  it("n'a plus de gestionnaire de clic, aucun mode", () => {
    assert.match(src, /data-testid="escale-legend-row"/);
    assert.match(src, /data-interactive="false"/);
    assert.doesNotMatch(src, /typeof onSeek === "function"/);
    assert.doesNotMatch(src, /onSeek=/);
    assert.doesNotMatch(src, /onClick/);
    assert.doesNotMatch(src, /<button/);
    assert.doesNotMatch(src, /cursor-pointer/);
    assert.match(src, /<div className="flex-1 min-w-0 text-left px-2 py-1 text-\[11px\] cursor-default"/);
    assert.match(src, /nmLabel/);
    assert.match(src, /dateLabel/);
    assert.match(src, /quayLabel/);
    assert.match(src, /etaLabel/);
    assert.doesNotMatch(tools, /onSeek=\{onSeekEscale\}/);
  });
});

describe("EscaleLegend — fourchette sous la date", () => {
  it("ajoute eta-range sans retirer la date", () => {
    assert.match(src, /data-testid="escale-legend"/);
    assert.match(src, /data-testid="eta-range"/);
    assert.match(src, /formatStopoverDate/);
    assert.match(src, /dateLabel/);
    assert.match(src, /formatEtaRange/);
    assert.match(src, /formatEtaRangeTitle/);
    assert.match(src, /useOfficialEta/);
    assert.match(src, /nextStopFromMarks/);
    assert.match(src, /nextStopRowIndex/);
    assert.match(src, /nextIndex/);
    assert.match(src, /title=\{etaTitle/);
  });
});

describe("EscaleLegend — fourchette ou raison", () => {
  it("garde eta-range pour la fourchette et la ligne de raison", () => {
    assert.match(src, /data-testid="eta-range"/);
    assert.match(src, /formatEtaRange/);
    assert.doesNotMatch(src, /en préparation/);
  });
});

describe("EscaleLegend — fourchette sur la prochaine", () => {
  it("pose eta-range sur nextStopFromMarks, pas le playhead", () => {
    assert.match(src, /nextStopRowIndex/);
    assert.match(src, /nextStopFromMarks/);
    assert.doesNotMatch(src, /playheadNext/);
    assert.doesNotMatch(src, /nextIndex = current \+ 1/);
  });
});

describe("EscaleLegend — ETA gelée pendant le film", () => {
  it("passe frozen à useOfficialEta", () => {
    assert.match(src, /frozen = false/);
    assert.match(src, /officialClock: officialEta/);
    assert.match(src, /useOfficialEta\(nextName,/);
  });
});

describe("EscaleLegend — pastilles de régime", () => {
  it("colore hindcast, prévision et climatologie depuis riskColors", () => {
    const colors = readFileSync(join(here, "..", "utils", "riskColors.js"), "utf8");
    assert.match(src, /regimeLegendHex/);
    assert.match(src, /data-testid="escale-regime-legend"/);
    assert.match(src, /data-testid="escale-regime-pill"/);
    assert.match(src, /data-regime=\{id\}/);
    assert.match(colors, /hindcast:\s*"#2dd4bf"/);
    assert.match(colors, /forecast:\s*"#38bdf8"/);
    assert.match(colors, /climatology:\s*"#c084fc"/);
    assert.doesNotMatch(src, /<button/);
  });
});

describe("EscaleLegend — nom affiché, identité stockée", () => {
  it("montre displayStopName et garde data-escale sur le nom brut", () => {
    assert.match(src, /label: displayStopName\(m\.name, lang, t\)/);
    assert.match(src, /data-escale=\{name\}/);
    assert.match(src, /\{label \|\| name\}/);
    assert.doesNotMatch(src, /data-escale=\{label\}/);
    const tFr = (key) => fr[key] ?? key;
    const tEn = (key) => en[key] ?? key;
    assert.equal(displayStopName("Saint-Maur (Berry, Indre)", "fr", tFr), "Saint-Maur (Indre)");
    assert.equal(displayStopName("Açores (Corse)", "fr", tFr), "Açores");
    assert.equal(displayStopName("Açores (Corse)", "en", tEn), "Azores (Portugal)");
    assert.equal(displayStopName("Ajaccio (Corse)", "fr", tFr), "Ajaccio (Corse)");
  });
});

describe("EscaleLegend — jambe live, pas le mur", () => {
  it("prend nowMs / liveFilmNm officiels, jamais Date.now()", () => {
    assert.doesNotMatch(src, /Date\.now\(\)/);
    assert.match(src, /nextStopFromMarks\(marks, nowMs, liveFilmNm\)/);
    assert.match(src, /nextStopRowIndex\(rows, marks, nowMs, liveFilmNm\)/);
    assert.match(src, /officialEta = false/);
    assert.match(src, /officialClock: officialEta/);
  });
});
