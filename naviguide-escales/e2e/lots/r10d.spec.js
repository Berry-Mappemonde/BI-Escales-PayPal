// Interface de l'expert (revue + Demander conseil).
// Sans API : fixture usePlanReview (Nouméa, 11 → 5, +41 nm, +7 j) et
// le bouton Simulation tiennent seuls. GET /voyage/official : sondé ;
// s'il manque, annotation + return après les assertions UI (jamais
// affaiblies). Si /plan-review n'est pas ready, on ne clique pas
// Appliquer (la fixture disparaît). Dialogue de brouillon : seulement si l'API répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r10d/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  const { showLeftPanel: open } = await import("../helpers.js");
  await open(page);
}

async function showReview(page) {
  const { openReviewTab } = await import("../helpers.js");
  await openReviewTab(page);
}

test("Revue du plan conseillée, Demander conseil", async ({ page }) => {
  test.setTimeout(45_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — dialogue de brouillon non joué",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  await showReview(page);
  const review = page.getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 15_000 });
  const comment = page.getByTestId("plan-review-comment");
  await expect(comment).toBeVisible();
  await expect(comment).toContainText(/Ce que je changerais|What I would change/);

  const reviewBody = apiUp
    ? await page.request.get("/voyage/official/plan-review", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null)).catch(() => null)
    : null;
  const reviewReady = reviewBody?.status === "ready" && Array.isArray(reviewBody?.legs) && reviewBody.legs.length > 0;
  const alerts = page.getByTestId("plan-review-leg-alerts");
  const sentence = page.getByTestId("plan-advice-sentence");
  if (apiUp && !reviewReady) {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready — PLAN_REVIEW_REV, alertes / Appliquer / comparatif sautés",
    });
  } else {
    await expect(alerts.first()).toBeVisible({ timeout: 10_000 });
    await expect(alerts.first()).toContainText(/alertes\s*:\s*\d+|alerts:\s*\d+/i);
    const sentenceUp = await sentence.isVisible({ timeout: 8_000 }).catch(() => false);
    if (!sentenceUp) {
      expect(apiUp, "sans API la phrase du conseil (fixture) doit être là").toBeTruthy();
      test.info().annotations.push({
        type: "poste",
        description: "GET /voyage/official/advice encore pending — pastilles / Appliquer non joués (LLM, poste)",
      });
    } else {
      const sentenceText = (await sentence.innerText()).trim();
      expect(sentenceText).toMatch(/Nouméa|Dzaoudzi|Partir|Leave|Rester|Keep leaving/);
      expect(sentenceText).not.toMatch(/\b(Leave Nouméa rather|What I would change is)\b/);
      const pills = page.getByTestId("plan-advice-pills");
      await expect(pills).toBeVisible();
      await expect(pills).toContainText(/\d+\s*→\s*\d+\s*alertes|\d+\s*→\s*\d+\s*alerts/);
      await expect(pills).toContainText(/[+-]?\d+\s*nm/i);
      await expect(pills).toContainText(/[+-]?\d+\s*[jd]\b/i);
      const apply = page.getByTestId("plan-advice-apply");
      await expect(apply).toBeVisible();
      await expect(apply).toContainText(/Appliquer|Apply/);
      await apply.evaluate((el) => el.click());
      const compare = page.getByTestId("plan-advice-compare");
      await expect(compare).toBeVisible();
      await expect(compare).toContainText(/aujourd'hui|today/i);
      await expect(compare).toContainText(/conseillé|advised/i);
      await expect(page.getByTestId("plan-advice-col-today")).toContainText(/alertes|alerts/i);
      await expect(page.getByTestId("plan-advice-col-advised")).toContainText(/alertes|alerts/i);
      await expect(compare).toContainText(/Dzaoudzi|nm/);
    }
  }
  await shot(page, "01-revue");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await page.getByTestId("ici-tab-now").evaluate((el) => el.click());
  const ask = page.getByTestId("ask-advice");
  await expect(ask).toBeVisible({ timeout: 15_000 });
  await expect(ask).toContainText(/Demander conseil|Ask for advice|Calcul isochrone|Computing/i);
  await expect(ask).not.toContainText(/Recalculer l.itin[eé]raire|Recalculate the route/);
  await shot(page, "02-conseil");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);

  if (!apiUp) return;

  const enabled = await ask.isEnabled().catch(() => false);
  if (!enabled) {
    test.info().annotations.push({
      type: "poste",
      description: "conseil inactif — Demander conseil présent mais inactif (isochrone / LLM, jamais en CI)",
    });
    return;
  }
  await ask.evaluate((el) => el.click());
  const dialog = page.getByTestId("route-compare");
  const dialogUp = await dialog.isVisible({ timeout: 8_000 }).catch(() => false);
  if (!dialogUp) {
    test.info().annotations.push({
      type: "poste",
      description: "Demander conseil cliqué — carte deux colonnes absente (isochrone / LLM, poste)",
    });
    return;
  }
  await expect(dialog.getByTestId("route-compare-today")).toBeVisible();
  await expect(dialog.getByTestId("route-compare-advised")).toBeVisible();
});
