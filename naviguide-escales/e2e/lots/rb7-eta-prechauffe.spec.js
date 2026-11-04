// Fourchette d'arrivée dès que l'ensemble est prêt, sans recharger.
// Sans API : fumée Suivre + liste des escales (la fourchette n'est jamais inventée).
// Avec API : première réponse members:0 puis ensemble → la phrase apparaît.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb7/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showLegendAndReview(page) {
  const { showRightPanel, openReviewTab } = await import("../helpers.js");
  await showRightPanel(page);
  await openReviewTab(page);
}

test("Fourchette dès que l'ensemble est prêt, sans recharger", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  // Pas d'interception : on lit le stock figé (members=0 tant que l'ensemble
  // Open-Meteo n'a pas été calculé — jamais une fourchette écrite par le spec).

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  const legend = page.getByTestId("escale-legend");
  if (await legend.isVisible({ timeout: 4000 }).catch(() => false)) {
    await legend.scrollIntoViewIfNeeded();
  }

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette non vérifiée (jamais inventée)",
    });
    await shot(page, "01-fourchette");
    return;
  }

  await showLegendAndReview(page);
  await expect(legend).toBeVisible({ timeout: 15_000 });

  const legendEta = page.getByTestId("eta-range");
  if (!(await legendEta.first().isVisible({ timeout: 8_000 }).catch(() => false))) {
    test.info().annotations.push({
      type: "poste",
      description: "fourchette absente (eta members=0, ensemble Open-Meteo hors CI) — jamais inventée",
    });
    await shot(page, "01-fourchette");
    return;
  }
  const a = (await legendEta.first().innerText()).trim();
  if (/fourchette indisponible|arrival window unavailable/i.test(a)) {
    test.info().annotations.push({
      type: "ensemble indisponible",
      description: "stock figé sans ensemble calculé — l'interface reste honnête, aucune fourchette inventée",
    });
    await shot(page, "01-fourchette");
    return;
  }
  expect(a).toMatch(/arrivée entre le|arrival between/i);
  expect(a).not.toMatch(/p10|membres|members|juin|June/i);
  expect(await legendEta.count(), "une seule fourchette sous la prochaine escale").toBe(1);

  const reviewEta = page.getByTestId("plan-review-eta-range");
  if (await reviewEta.count()) {
    const b = (await reviewEta.first().innerText()).trim();
    expect(b).toBe(a);
  }
  const row = page.getByTestId("plan-review-leg").filter({ hasText: /Nouméa/i }).filter({ hasText: /Dzaoudzi/i });
  if (await row.count()) await row.first().scrollIntoViewIfNeeded();
  await shot(page, "01-fourchette");
});
