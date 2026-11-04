// Barre film compacte, un seul bouton son.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-o/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function assertOneListen(bar) {
  await expect(bar.getByTestId("listen")).toHaveCount(1);
  await expect(bar.locator("[data-testid='replay-voice']")).toHaveCount(0);
  const height = await bar.evaluate((el) => el.getBoundingClientRect().height);
  expect(height, `hauteur barre = ${height}px`).toBeLessThanOrEqual(96);
}

test("Un seul Écouter, pas de replay-voice, barre ≤ 96 px", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const bar = page.getByTestId("film-bar");
  await expect(bar).toBeVisible();

  // Accueil Suivre ; la barre se vérifie aussi en Simulation.
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await assertOneListen(bar);
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await assertOneListen(bar);
  await shot(page, "02-simulation");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(bar.getByTestId("replay-start")).toBeVisible();
  await assertOneListen(bar);
  await shot(page, "01-suivre");
});
