// Script du film : chapitre 1 Saint-Maur + La Rochelle, source visible.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-f3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Chapitre 1 Saint-Maur / La Rochelle, source non vide", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });

  await page.getByTestId("replay-start").click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await expect(subtitle).toContainText("Saint-Maur");
  await expect(subtitle).toContainText("La Rochelle");
  await shot(page, "01-chapitre-1");

  // « Récit : règles » retiré de la barre ; la source reste dans le DOM (hidden).
  const source = page.getByTestId("film-source");
  await expect(source).toBeAttached();
  await expect(source).toHaveAttribute("hidden", "");
  const text = (await source.innerText()).trim();
  expect(text, "film-source ne doit pas être vide").not.toBe("");
  await shot(page, "02-source");
});
