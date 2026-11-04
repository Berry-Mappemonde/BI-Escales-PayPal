// Résumé d'expédition : étapes entre escales, plus les sommets du routeur.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showRightPanel } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-c1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Résumé : 16 étapes · 17 escales, sans « waypoints »", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await showRightPanel(page);
  const summary = page.getByTestId("route-summary");
  await expect(summary).toBeVisible({ timeout: 30_000 });
  await expect(summary).toContainText("16 étapes", { timeout: 30_000 });
  await expect(summary).toContainText("17 escales");
  await expect(summary).not.toContainText(/waypoints/i);
  await shot(page, "01-resume");
});
