import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { adviceApplyDisabled } from "../engine/planReview.js";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "PlanReview.jsx"), "utf8");
const tools = readFileSync(join(here, "ToolsSidebar.jsx"), "utf8");
const ici = readFileSync(join(here, "IciMaintenant.jsx"), "utf8");
const sidebar = readFileSync(join(here, "Sidebar.jsx"), "utf8");
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");

describe("PlanReview — commentaire", () => {
  it("affiche le paragraphe sous le tableau avec source i18n", () => {
    assert.match(src, /data-testid="plan-review-comment"/);
    assert.match(src, /planReviewCommentTitle/);
    assert.match(src, /LlmSourceBadge/);
    assert.match(src, /plan-review-source/);
    assert.match(src, /commentSource/);
    assert.doesNotMatch(src, /Nemotron|Tavily|Nebius/);
  });

  it("reçoit le commentaire depuis la revue serveur, sans retirer le tableau", () => {
    assert.match(app, /planReviewState\.review\?\.comment\?\.text/);
    assert.match(app, /planReviewState\.review\?\.comment\?\.source/);
    assert.match(ici, /comment=\{planReview\.comment\}/);
    assert.match(ici, /<PlanReview[\s\S]*legs=\{planReview\.legs\}/);
    assert.match(sidebar, /planReview=\{!drawingHidesBerry \? planReview : null\}/);
    assert.match(app, /planReview=\{planReview\}/);
    assert.doesNotMatch(tools, /<PlanReview/);
    assert.doesNotMatch(tools, /planReview && !drawing/);
    assert.match(src, /data-testid="plan-review"/);
    assert.match(src, /data-testid="plan-review-leg"/);
    assert.match(src, /data-testid="plan-review-leg-dates"/);
    assert.match(src, /data-testid="plan-review-eta-range"/);
    assert.match(src, /formatEtaRange/);
    assert.match(src, /formatEtaRangeTitle/);
    assert.match(src, /title=\{etaTitle/);
  });
});

describe("PlanReview — conseil", () => {
  it("montre alertes par jambe, phrase, pastilles et deux colonnes", () => {
    assert.match(src, /planReviewLegAlerts/);
    assert.match(src, /data-testid="plan-review-leg-alerts"/);
    assert.match(src, /data-testid="plan-advice-sentence"/);
    assert.match(src, /data-testid="plan-advice-pills"/);
    assert.match(src, /data-testid="plan-advice-apply"/);
    assert.match(src, /data-testid="plan-advice-compare"/);
    assert.match(src, /planCompareToday/);
    assert.match(src, /planCompareAdvised/);
    assert.match(src, /localizeAdviceSentence/);
    assert.match(src, /formatAdvicePills/);
    assert.doesNotMatch(src, /alternatives/);
    assert.doesNotMatch(src, /six routes/);
  });

  it("désactive Appliquer quand la date proposée est passée", () => {
    assert.match(src, /adviceApplyDisabled/);
    assert.match(src, /disabled=\{applyOff\}/);
    const now = Date.parse("2026-10-18T12:00:00Z");
    const past = { facts: ["départ 2026-05-01 → 2026-05-15"], shiftDays: 0 };
    assert.equal(adviceApplyDisabled(past, now), true);
    const future = { departIso: "2026-12-01T08:00:00Z", shiftDays: 7 };
    assert.equal(adviceApplyDisabled(future, now), false);
  });

  it("ne rend pas le commentaire LLM à la place de la phrase du conseil", () => {
    const sentenceAt = src.indexOf("plan-advice-sentence");
    const commentRender = src.indexOf("{comment}");
    assert.ok(sentenceAt > 0);
    assert.equal(commentRender, -1, "comment.text n'est plus affiché (anglais vu le 22 sept.)");
  });
});

describe("PlanReview — pastille anti-trafic", () => {
  it("affiche les couloirs sous la jambe, sans encadré jaune route", () => {
    assert.match(src, /data-testid="plan-review-lanes"/);
    assert.match(src, /planReviewLanes/);
    assert.match(src, /antiShipping/);
    assert.match(src, /0\.55/);
    assert.doesNotMatch(tools, /data-testid="route-anti-shipping"/);
    assert.doesNotMatch(tools, /viewRouteAntiShipping/);
    assert.match(tools, /data-testid="polar-boat"/);
    assert.doesNotMatch(src, /Le score anti-trafic|hors des couloirs|aide/);
  });
});

describe("PlanReview — légende des régimes", () => {
  it("pose une ligne discrète au-dessus du tableau, pas dans la barre", () => {
    assert.match(src, /data-testid="plan-review-regime-legend"/);
    const legendAt = src.indexOf('data-testid="plan-review-regime-legend"');
    const tableAt = src.indexOf("<ul");
    assert.ok(legendAt > 0 && legendAt < tableAt, "légende au-dessus du tableau");
    assert.match(src, /clockRegimeHindcast/);
    assert.match(src, /clockRegimeForecast/);
    assert.match(src, /clockRegimeClimatology/);
  });
});
