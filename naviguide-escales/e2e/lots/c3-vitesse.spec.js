// Une seule vitesse (barre = horloge = debug) ; légende des régimes.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-c3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function knotsIn(text) {
  const m = String(text || "").match(/(\d+[.,]\d+)\s*kt/);
  return m ? Number(m[1].replace(",", ".")) : null;
}

test("Vitesse unique et légende des régimes", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const clock = page.getByTestId("clock-line");
  await expect(clock).toBeVisible({ timeout: 15_000 });
  const legend = page.getByTestId("regime-legend");
  await expect(legend).toBeVisible({ timeout: 15_000 });
  // RC18 / RF10 : le libellé visible est la vitesse ; les trois régimes sont dans title / aria-label.
  await expect(legend).toHaveAttribute("title", /hindcast/i);
  await expect(legend).toHaveAttribute("title", /prévision|forecast/i);
  await expect(legend).toHaveAttribute("title", /climatolog/i);
  await expect(legend).toHaveAttribute("aria-label", /hindcast/i);

  const line = await clock.innerText();
  const debug = await page.evaluate(() => window.__naviguideDebug || null);
  expect(debug, "window.__naviguideDebug exposé").toBeTruthy();
  if (/à quai|in port/i.test(line)) {
    expect(debug.atQuay).toBeTruthy();
    expect(debug.speed === 0 || debug.speed == null).toBeTruthy();
    await expect(clock).not.toContainText(/\d+[.,]\d+\s*kt/);
  } else {
    const kn = knotsIn(line);
    expect(kn, `kn dans clock-line : ${line}`).not.toBeNull();
    expect(Number(debug.speed)).toBeCloseTo(kn, 1);
  }
  await shot(page, "01-legende");
});
