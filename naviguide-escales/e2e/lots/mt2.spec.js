// Calques météo : Suivre et Tracer restent utilisables, chaque couche
// s'allume, un fournisseur injoignable ne fige pas l'écran.
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas,
// annotation + return des assertions de popup. Barre, Suivre, Tracer
// et les cinq boutons de couche restent exigés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-mt2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LAYERS = [
  ["grib2", "GRIB2"],
  ["climo-wind", "Vent"],
  ["climo-wave", "Houle"],
  ["climo-current", "Courants"],
  ["climo-cyclones", "Cyclones"],
];

async function openLayers(page) {
  const drawer = page.getByTestId("layers-drawer");
  if (!(await drawer.locator("summary").isVisible().catch(() => false))) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
    await expect(drawer.locator("summary")).toBeVisible({ timeout: 10_000 });
  }
  await drawer.locator("summary").scrollIntoViewIfNeeded();
  if (!(await drawer.evaluate((el) => el.open))) await drawer.locator("summary").click();
  await expect(drawer.getByTestId("layer-toggles")).toBeVisible();
}

test("Suivre, Tracer et les calques météo ne figent pas l'écran", async ({ page }) => {
  test.setTimeout(60_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const official = await page.request.get("/voyage/official", { timeout: 5_000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const suivre = page.getByTestId("view-suivre");
  const tracer = page.getByTestId("view-tracer");
  await expect(suivre).toBeVisible();
  await expect(suivre).toContainText("Suivre");
  await expect(tracer).toBeVisible();
  await expect(tracer).toContainText("Tracer");

  await tracer.click();
  await expect(tracer).toHaveAttribute("aria-checked", "true");
  await suivre.click();
  await expect(suivre).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();

  await openLayers(page);
  for (const [key, label] of LAYERS) {
    const btn = page.getByTestId(`layer-${key}`);
    await btn.scrollIntoViewIfNeeded();
    await expect(btn).toBeVisible();
    await expect(btn).toContainText(label);
    await btn.click({ timeout: 5_000 });
    await expect(btn).toHaveAttribute("aria-pressed", "true", { timeout: 5_000 });
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 5_000 });
    await expect(suivre).toBeVisible();
  }

  await shot(page, "01-suivre-calques");
  await tracer.click();
  await expect(tracer).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await shot(page, "02-tracer-calques");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — popup météo sauté ; Suivre, Tracer et calques gardés",
    });
    return;
  }

  const atlas = await page.request.get("/bi/climatology/point?lat=46.15&lon=-1.16&month=10", { timeout: 8_000 }).catch(() => null);
  if (!atlas || !atlas.ok()) {
    test.info().annotations.push({
      type: "atlas coupé",
      description: "GET /bi/climatology/point absent — popup sauté ; Suivre, Tracer et calques gardés",
    });
    return;
  }

  await suivre.click();
  await expect(suivre).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  const map = page.locator(".leaflet-container").first();
  await expect(map).toBeVisible();
  const box = await map.boundingBox();
  expect(box, "carte mesurable").toBeTruthy();
  await map.click({
    position: { x: Math.round(box.width * 0.35), y: Math.round(box.height * 0.45) },
    timeout: 5_000,
  });
  const popup = page.locator("[data-testid='climatology-map-popup'], [data-testid='climatology-popup']").first();
  await expect(popup).toBeVisible({ timeout: 15_000 });
  const text = (await popup.innerText()).replace(/\s+/g, " ");
  expect(text).toMatch(/Climatologie/);
  expect(text).toMatch(/\d+(?:[.,]\d+)?\s*(?:kn|m|°)/);
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await shot(page, "03-popup-case");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
