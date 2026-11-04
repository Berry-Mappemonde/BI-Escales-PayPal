// Accueil et retour Suivre : bateau au centre, monde dézoomé
// (plancher : un seul monde). Sans API : GET /voyage/official sondé ; s'il
// ne répond pas, annotation + saut des assertions bateau-au-centre — jamais
// le zoom plancher, ni Suivre, ni Tracer, ni le Cinéma.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  cinemaPressed,
  dismissNotForNav,
  mapFollowCadrage,
  mapZoom,
  probeOfficial,
} from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm4");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function expectFloorZoom(page) {
  await expect.poll(async () => {
    const z = await mapZoom(page);
    return Number.isFinite(z) ? z : 99;
  }, { timeout: 12_000 }).toBeGreaterThanOrEqual(2.4);
  await expect.poll(async () => {
    const z = await mapZoom(page);
    return Number.isFinite(z) ? z : 99;
  }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);
}

async function expectBoatAtCenter(page) {
  await expect.poll(async () => {
    const s = await mapFollowCadrage(page);
    return Number.isFinite(s?.zoom) ? s.zoom : 99;
  }, { timeout: 15_000 }).toBeGreaterThanOrEqual(2.4);
  await expect.poll(async () => {
    const s = await mapFollowCadrage(page);
    return Number.isFinite(s?.zoom) ? s.zoom : 99;
  }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);
  await expect.poll(async () => {
    const s = await mapFollowCadrage(page);
    return Number.isFinite(s?.boatPx) ? s.boatPx : 9999;
  }, { timeout: 25_000 }).toBeLessThan(80);
}

test("Accueil et retour Suivre : bateau au centre, zoom plancher", async ({ page }) => {
  test.setTimeout(90_000);

  const officialBody = await probeOfficial(page);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — bateau au centre sauté ; zoom plancher et modes conservés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  expect(await cinemaPressed(page), "Cinéma enfoncé au chargement").toBe(true);

  const mapReady = await page.waitForFunction(() => window.__naviguideScene?.map, null, { timeout: 20_000 })
    .then(() => true)
    .catch(() => false);
  expect(mapReady, "carte montée").toBe(true);
  await expectFloorZoom(page);
  if (apiUp) {
    await page.waitForFunction(() => (
      Boolean(window.__naviguideScene?.config?.live?.lat)
      || Boolean(document.querySelector(".catamaran-divicon"))
    ), null, { timeout: 25_000 }).catch(() => {});
    await expectBoatAtCenter(page);
  }
  await shot(page, "01-accueil");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => cinemaPressed(page), { timeout: 8_000 }).toBe(false);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  expect(await cinemaPressed(page), "retour Suivre : Cinéma enfoncé").toBe(true);
  await expectFloorZoom(page);
  if (apiUp) await expectBoatAtCenter(page);
  await shot(page, "02-retour-suivre");

  if (!apiUp) return;

  const box = await page.locator(".leaflet-container").boundingBox();
  expect(box).toBeTruthy();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5 + 220, box.y + box.height * 0.45 + 90, { steps: 10 });
  await page.mouse.up();
  await expect.poll(async () => {
    const s = await mapFollowCadrage(page);
    return Number.isFinite(s?.boatPx) ? s.boatPx : 0;
  }, { timeout: 8_000 }).toBeGreaterThan(80);

  await page.getByTestId("view-suivre").click();
  await expectFloorZoom(page);
  await expectBoatAtCenter(page);
});
