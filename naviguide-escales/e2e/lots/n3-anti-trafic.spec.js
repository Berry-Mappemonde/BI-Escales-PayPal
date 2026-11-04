// Score anti-trafic (pastille « couloirs : Gibraltar »).
// Sans API : fixture usePlanReview (Ajaccio → Fort-de-France, Gibraltar).
// GET /voyage/official : sondé ; s'il manque, annotation seulement —
// les pastilles fixture ne sont pas affaiblies. Si l'API répond mais
// /plan-review n'est pas ready (RC50, PLAN_REVIEW_REV), annotation +
// saut des pastilles — le contrat Gibraltar reste dur dès que ready.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficialPlanReview } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-n3/${name}.webp`,
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

async function showReview(page) {
  const { openReviewTab } = await import("../helpers.js");
  await openReviewTab(page);
}

/** L'horloge live à quai ouvre la fiche d'escale → onglet Maintenant. */
async function keepReviewOpen(page) {
  const tab = page.getByTestId("ici-tab-review");
  if ((await tab.getAttribute("aria-selected")) !== "true") {
    await tab.evaluate((el) => el.click());
  }
}

test("Revue du plan : couloirs Gibraltar sous Ajaccio → Fort-de-France", async ({ page }) => {
  test.setTimeout(45_000);
  const { apiUp, reviewReady, legs } = await probeOfficialPlanReview(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — pastilles servies par la fixture (jamais affaiblies)",
    });
  } else if (!reviewReady) {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready — PLAN_REVIEW_REV, pastilles Gibraltar sautées",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });

  await showReview(page);
  await keepReviewOpen(page);
  const review = page.getByTestId("ici-review-slot").getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 15_000 });

  if (apiUp && !reviewReady) {
    await shot(page, "01-couloirs");
    expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
    return;
  }

  const row = review.getByTestId("plan-review-leg").filter({ hasText: /Ajaccio/i }).filter({ hasText: /Fort-de-France/i });
  await expect.poll(async () => {
    await keepReviewOpen(page);
    return row.count();
  }, { timeout: 20_000 }).toBeGreaterThan(0);
  await row.first().scrollIntoViewIfNeeded();
  const lanes = row.getByTestId("plan-review-lanes");

  const officialPack = (legs || []).find((l) => /Ajaccio/i.test(l.from || "") && /Fort-de-France/i.test(l.to || ""))?.antiShipping || null;

  await expect.poll(async () => {
    await keepReviewOpen(page);
    return lanes.count();
  }, { timeout: 15_000 }).toBeGreaterThan(0);
  await expect(lanes.first()).toBeVisible();
  await expect(lanes.first()).toContainText(/couloirs\s*:\s*Gibraltar|lanes\s*:\s*Gibraltar|Gibraltar/);
  if (apiUp) {
    expect(Array.isArray(officialPack?.lanes) && officialPack.lanes.includes("Gibraltar"), "antiShipping Gibraltar du stock").toBeTruthy();
    expect(Number(officialPack.score)).toBeLessThan(1);
  }
  await shot(page, "01-couloirs");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
