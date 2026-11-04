// Conventions : info-bulle sur la distance (saut avion exclu).
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showRightPanel } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-c7/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Survol de la distance : title non vide", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await showRightPanel(page);
  const summary = page.getByTestId("route-summary");
  await expect(summary).toBeVisible({ timeout: 30_000 });
  const title = await summary.getAttribute("title");
  expect(title, "title sur route-summary").toBeTruthy();
  expect(String(title).trim().length).toBeGreaterThan(0);
  await summary.hover();
  await shot(page, "01-infobulle");
});
