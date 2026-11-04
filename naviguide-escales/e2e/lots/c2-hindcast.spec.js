// Horloge à trois régimes. Sans API : fumée barre film.
// Avec API et hindcast prêt : clock-regime contient « hindcast » et « sources ».
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-c2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Régime sur la barre film", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await shot(page, "01-regime");

  const regime = page.getByTestId("clock-regime");
  let api = null;
  try {
    const r = await page.request.get("/voyage/official/regimes");
    if (r.ok()) api = await r.json();
  } catch {
    api = null;
  }
  if (api) {
    await expect(regime).toBeVisible({ timeout: 15_000 });
    const text = await regime.innerText();
    expect(text).toMatch(/hindcast|forecast|prévision|climatolog/i);
    if (api.hindcastStatus === "ready") {
      expect(text).toMatch(/hindcast/i);
      expect(text).toMatch(/sources/i);
    }
  } else {
    await expect(page.getByTestId("film-bar")).toBeVisible();
  }
});
