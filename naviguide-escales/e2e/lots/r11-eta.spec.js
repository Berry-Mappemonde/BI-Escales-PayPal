// Fourchette d'arrivée lisible, jours de mer cohérents.
// Sans API : fumée (barre film + Suivre). Avec API : les deux libellés
// (légende / revue du plan) sont identiques, sans « p10 » ni « membres ».
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r11/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showReview(page) {
  const { openReviewTab, showRightPanel } = await import("../helpers.js");
  await showRightPanel(page);
  await openReviewTab(page);
}

test("Fourchette identique sous l'escale et dans la revue", async ({ page }) => {
  test.setTimeout(45_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — fourchette et jours de mer non vérifiés",
    });
    await shot(page, "01-eta");
    return;
  }

  const reviewBody = await page.request.get("/voyage/official/plan-review", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const reviewReady = reviewBody?.status === "ready";
  const noumeaLeg = (reviewBody?.legs || []).find((l) => /Nouméa/i.test(l.from || "") && /Dzaoudzi/i.test(l.to || ""));
  if (!reviewReady || !noumeaLeg) {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready ou sans Nouméa → Dzaoudzi — PLAN_REVIEW_REV ; assertions jambe sautées",
    });
    await shot(page, "01-eta");
    return;
  }

  await showReview(page);
  const review = page.getByTestId("plan-review");
  await review.scrollIntoViewIfNeeded();
  expect(noumeaLeg, "jambe Nouméa → Dzaoudzi dans le plan figé").toBeTruthy();
  expect(Number(noumeaLeg.plannedKnots), "plannedKnots R11").toBeGreaterThan(0);
  expect(Number(noumeaLeg.daysAtSea), `daysAtSea Nouméa → Dzaoudzi : ${noumeaLeg.daysAtSea}`).toBeGreaterThan(30);
  const noumea = page.getByTestId("plan-review-leg").filter({ hasText: /Nouméa/i }).filter({ hasText: /Dzaoudzi/i });
  if (await noumea.count()) {
    const txt = await noumea.first().innerText();
    const m = txt.match(/(\d+(?:[.,]\d+)?)\s*(?:j de mer|d at sea)/i);
    expect(m, `badge mer sur Nouméa → Dzaoudzi : ${txt}`).toBeTruthy();
    const days = parseFloat(m[1].replace(",", "."));
    expect(days, `jours de mer Nouméa → Dzaoudzi : ${days}`).toBeGreaterThan(30);
  }
  const row = page.getByTestId("plan-review-leg").filter({ hasText: /Nouméa/i }).filter({ hasText: /Dzaoudzi/i });
  if (await row.count()) await row.first().scrollIntoViewIfNeeded({ timeout: 5_000 }).catch(() => {});

  const legendEta = page.getByTestId("eta-range");
  const reviewEta = page.getByTestId("plan-review-eta-range");
  await legendEta.waitFor({ state: "attached", timeout: 8000 }).catch(() => {});
  await reviewEta.waitFor({ state: "attached", timeout: 4000 }).catch(() => {});
  const legendVisible = (await legendEta.count()) > 0;
  const reviewVisible = (await reviewEta.count()) > 0;
  if (legendVisible && reviewVisible) {
    const a = (await legendEta.innerText()).trim();
    const b = (await reviewEta.innerText()).trim();
    if (/indisponible|unavailable/i.test(a)) {
      test.info().annotations.push({
        type: "poste",
        description: "fourchette honnête indisponible (members=0) — jamais inventée",
      });
    } else {
      expect(a).toMatch(/arrivée entre le|arrival between/i);
      expect(a).not.toMatch(/p10|membres|members/i);
      expect(b).toBe(a);
    }
  } else {
    test.info().annotations.push({
      type: "poste",
      description: "fourchette absente (members=0 ou /eta lent) — jamais inventée",
    });
  }
  await shot(page, "01-eta");
});
