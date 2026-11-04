// Revue commentée : paragraphe sous le tableau (texte ou « règles »).
// Sans API : source = règles. Recette réelle (Nemotron Super) : NEBIUS_API_KEY.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openReviewTab } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-l5/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Plan-review-comment : texte ou règles", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await openReviewTab(page);
  const review = page.getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 15_000 });
  const comment = page.getByTestId("plan-review-comment");
  await comment.scrollIntoViewIfNeeded();
  await expect(comment).toBeVisible();
  const text = (await comment.innerText()).trim();
  expect(text, "plan-review-comment ne doit pas être vide").not.toBe("");
  expect(text).toMatch(/Ce que je changerais|What I would change|règles|rules|données brutes|raw data/i);
  await shot(page, "01-commentaire");
});
