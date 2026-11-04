// Balisage, Bathymétrie, Fonds et Câbles s'allument au clic, vue monde comprise.
// Sans API : le cadenas et les tuiles posées sur la carte tiennent seuls.
// GET /voyage/official est sondé ; s'il ne répond pas, annotation et saut
// des seules assertions qui en dépendraient — le bouton et les tuiles restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { leaveCinema } from "../helpers.js";
import { NOT_FOR_NAV_STORAGE_KEY, NOT_FOR_NAV_VERSION } from "../../src/utils/notForNav.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/rx1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const PANES = {
  balisage: "balisage",
  bathymetry: "science-wms-bathy",
  fonds: "science-wms-substrate",
  cables: "science-wms-cables",
};

const LAYERS = ["balisage", "bathymetry", "fonds", "cables"];

async function probeOfficial(page) {
  const official = await page.request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  const up = Boolean(official && official.ok());
  if (!up) {
    test.info().annotations.push({
      type: "api",
      description: "GET /voyage/official ne répond pas : aucune assertion du voyage n'est jouée",
    });
  }
  return up;
}

async function openLayers(page) {
  await leaveCinema(page);
  const panel = page.locator(".naviguide-sidebar-panel.right-0").first();
  const closed = await panel.evaluate((el) => el.className.includes("translate-x-full")).catch(() => true);
  if (closed) {
    await page.locator(".naviguide-sidebar-toggle--right").evaluate((el) => el.click());
  }
  await expect.poll(() => panel.evaluate((el) => el.className.includes("translate-x-full"))).toBe(false);
  const drawer = page.getByTestId("layers-drawer");
  await drawer.locator("summary").scrollIntoViewIfNeeded();
  if (!(await drawer.evaluate((el) => Boolean(el.open)).catch(() => false))) {
    await drawer.locator("summary").click();
  }
  await expect(page.getByTestId("layer-balisage")).toBeVisible();
}

async function parkOnWorld(page) {
  await page.evaluate(() => {
    window.__naviguideScene.map.fire("dragstart");
  });
  await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    map.setView([22, 5], map.getMinZoom(), { animate: false });
  });
  await expect.poll(() => page.evaluate(() => {
    const map = window.__naviguideScene.map;
    return Math.abs(map.getZoom() - map.getMinZoom()) <= 0.01;
  })).toBe(true);
}

function placedTiles(page, key) {
  return page.evaluate((name) => {
    const map = window.__naviguideScene.map;
    let layers = 0;
    map.eachLayer((lyr) => {
      if (lyr.options?.pane === name) layers += 1;
    });
    const node = map.getPane(name);
    const imgs = node ? node.querySelectorAll("img").length : 0;
    return {
      layers,
      imgs,
      zoom: map.getZoom(),
      min: map.getMinZoom(),
    };
  }, PANES[key]);
}

async function expectLit(page, key) {
  const btn = page.getByTestId(`layer-${key}`);
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => {
    const placed = await placedTiles(page, key);
    return placed.layers >= 1
      && placed.imgs >= 1
      && Math.abs(placed.zoom - placed.min) <= 0.01;
  }, { timeout: 8_000 }).toBe(true);
}

test("sans accord : le dialogue puis le calque allumé, vue monde", async ({ page }) => {
  test.setTimeout(60_000);
  await probeOfficial(page);
  await page.addInitScript((key) => {
    localStorage.removeItem(key);
  }, NOT_FOR_NAV_STORAGE_KEY);
  await page.goto("/");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await openLayers(page);
  await parkOnWorld(page);

  const balisage = page.getByTestId("layer-balisage");
  await balisage.scrollIntoViewIfNeeded();
  await expect(balisage).toHaveAttribute("aria-pressed", "false");
  await balisage.click();

  const modal = page.getByTestId("not-for-nav-modal");
  await expect(modal).toBeVisible();
  await expect(modal).toContainText("Ne convient pas à la navigation.");
  await expect(balisage).toHaveAttribute("aria-pressed", "false");
  await shot(page, "01-dialogue");

  await page.getByTestId("not-for-nav-ack").check();
  await page.getByTestId("not-for-nav-accept").click();
  await expect(modal).toBeHidden();
  await expectLit(page, "balisage");
  await shot(page, "02-balisage-monde");

  for (const key of ["bathymetry", "fonds", "cables"]) {
    const btn = page.getByTestId(`layer-${key}`);
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    await expect(modal).toBeHidden();
    await expectLit(page, key);
  }

  await balisage.click();
  await expect(balisage).toHaveAttribute("aria-pressed", "false");
  await balisage.click();
  await expectLit(page, "balisage");
});

test("accord déjà donné : le premier clic enfonce le bouton, vue monde", async ({ page }) => {
  test.setTimeout(60_000);
  await probeOfficial(page);
  await page.addInitScript(([key, version]) => {
    localStorage.setItem(key, JSON.stringify({ version, at: "2026-10-19T12:00:00.000Z" }));
  }, [NOT_FOR_NAV_STORAGE_KEY, NOT_FOR_NAV_VERSION]);
  await page.goto("/");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await openLayers(page);
  await parkOnWorld(page);

  const modal = page.getByTestId("not-for-nav-modal");
  for (const key of LAYERS) {
    const btn = page.getByTestId(`layer-${key}`);
    await btn.scrollIntoViewIfNeeded();
    await expect(btn).toHaveAttribute("aria-pressed", "false");
    await btn.click();
    await expect(modal).toBeHidden();
    await expectLit(page, key);
  }
  await shot(page, "03-accord-monde");

  const balisage = page.getByTestId("layer-balisage");
  await balisage.click();
  await expect(balisage).toHaveAttribute("aria-pressed", "false");
  await balisage.click();
  await expectLit(page, "balisage");
});
