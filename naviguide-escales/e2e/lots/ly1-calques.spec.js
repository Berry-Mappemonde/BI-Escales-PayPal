// NAV-D-14 : tous les calques actifs, aucun longtask > 1 s au zoom.
// Les catalogues sont fournis par la page (pas d'appel BI). GET /voyage/official
// est sondé ; s'il ne répond pas, annotation et saut de la seule réouverture
// de fiche — le plafond de longtask et le bouton Capitainerie restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ly1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LAYER_KEYS = [
  "grib2", "zee", "wpi", "balisage", "projects", "marinas", "capitaineries",
  "poe", "amp", "sextant", "argo", "odatis", "edmed", "csr",
  "bathymetry", "fonds", "cables",
  "climo-wind", "climo-wave", "climo-current", "climo-cyclones",
];

function pointFeatures(n) {
  const features = [{
    type: "Feature",
    properties: { name: "zone" },
    geometry: { type: "Polygon", coordinates: [[[-2, 46], [-1, 46], [-1, 47], [-2, 46]]] },
  }];
  for (let i = 0; i < n; i += 1) {
    features.push({
      type: "Feature",
      properties: { naviguideCatalogId: `p${i}` },
      geometry: {
        type: "Point",
        coordinates: [-40 + (i % 40) * 0.15, 10 + Math.floor(i / 40) * 0.15],
      },
    });
  }
  return features;
}

const CATALOG = {
  type: "FeatureCollection",
  features: pointFeatures(240),
  metadata: { total: 240, matched: 240, rendered: 240 },
};

const EMPTY_HARBOUR = {
  type: "FeatureCollection",
  features: [],
  metadata: { total: 0, matched: 0, rendered: 0 },
};

const ROSES = {
  type: "FeatureCollection",
  features: pointFeatures(180).filter((f) => f.geometry.type === "Point").map((f) => ({
    ...f,
    properties: {
      speed_knots: 12,
      dir_from_deg: 40,
      wind_speed_knots: 12,
      wind_direction_from_deg: 40,
    },
  })),
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ly1Long = [];
    try {
      const obs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__ly1Long.push(entry.duration);
      });
      obs.observe({ type: "longtask", buffered: true });
    } catch {
      /* longtask indisponible : le test le verra vide et ne relâche pas le plafond */
    }
  });
  await page.route("**/proxy/**", async (route) => {
    const url = route.request().url();
    if (url.includes("capitaineries")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_HARBOUR) });
      return;
    }
    if (url.includes("/proxy/catalog/") || url.includes("/proxy/ports")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CATALOG) });
      return;
    }
    await route.fulfill({ status: 204, body: "" });
  });
  await page.route("**/*climatology*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ROSES) });
  });
  await page.route(/blueintelligence|openseamap|geoserver/i, (route) => route.abort());
});

async function openLayers(page) {
  await dismissNotForNav(page);
  await showRightPanel(page);
  const drawer = page.getByTestId("layers-drawer");
  await drawer.locator("summary").scrollIntoViewIfNeeded();
  if (!(await drawer.evaluate((el) => el.open).catch(() => false))) {
    await drawer.locator("summary").click();
  }
  await expect(page.getByTestId("layer-toggles")).toBeVisible();
}

async function pressLayer(page, key) {
  const btn = page.getByTestId(`layer-${key}`);
  await btn.scrollIntoViewIfNeeded();
  if (await btn.isDisabled()) return;
  if ((await btn.getAttribute("aria-pressed")) === "true") return;
  await btn.click();
  const modal = page.getByTestId("not-for-nav-modal");
  if (await modal.isVisible().catch(() => false)) {
    const ack = page.getByTestId("not-for-nav-ack");
    if (await ack.isVisible().catch(() => false)) await ack.check();
    await page.getByTestId("not-for-nav-accept").click();
    if ((await btn.getAttribute("aria-pressed")) !== "true" && !(await btn.isDisabled())) {
      await btn.click();
    }
  }
}

test("tous les calques tiennent un zoom sans longtask d'une seconde", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await leaveCinema(page);
  await openLayers(page);
  await shot(page, "01-calques");

  for (const key of LAYER_KEYS) {
    await pressLayer(page, key);
  }

  const harbour = page.getByTestId("layer-capitaineries");
  await expect(harbour).toBeDisabled();
  await expect(harbour).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("layer-toggles")).not.toContainText("502");

  for (const key of LAYER_KEYS) {
    if (key === "capitaineries") continue;
    await expect(page.getByTestId(`layer-${key}`)).toHaveAttribute("aria-pressed", "true");
  }

  await shot(page, "02-calques-actifs");
  await page.evaluate(() => window.__ly1Long.splice(0, window.__ly1Long.length));
  await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    map.setZoom(Math.min(map.getZoom() + 1, map.getMaxZoom()));
  });
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    map.setZoom(Math.max(map.getZoom() - 1, map.getMinZoom()));
  });
  await page.waitForTimeout(800);
  const durations = await page.evaluate(() => window.__ly1Long.slice());
  const worst = durations.reduce((max, n) => Math.max(max, Number(n) || 0), 0);
  expect(worst).toBeLessThanOrEqual(1000);

  const official = await page.request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  if (!official || !official.ok()) {
    test.info().annotations.push({
      type: "api",
      description: "GET /voyage/official ne répond pas : réouverture de la fiche d'escale non jouée",
    });
    return;
  }
  // Le premier drapeau (Saint-Maur) peut être sous le panneau de droite quand la caméra suit
  // le bateau : un clic forcé tombe alors sur le panneau. On prend le premier drapeau dégagé.
  const freeIdx = await page.evaluate(() => [...document.querySelectorAll("[data-testid='waypoint-flag']")]
    .findIndex((el) => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return false;
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return Boolean(top && el.contains(top));
    }));
  const flags = page.locator("[data-testid='waypoint-flag']");
  if (!(await flags.count())) {
    test.info().annotations.push({
      type: "api",
      description: "parcours officiel sans drapeau cliquable : fiche d'escale non jouée",
    });
    return;
  }
  // Des drapeaux existent : au moins un doit être dégagé, sinon c'est un défaut.
  expect(freeIdx, "aucun drapeau dégagé (tous sous un panneau)").toBeGreaterThanOrEqual(0);
  const flag = flags.nth(freeIdx);
  await flag.click({ force: true });
  const sheet = page.getByTestId("escale-sheet");
  await expect(sheet).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("escale-close").click();
  await expect(sheet).toBeHidden();
  const started = Date.now();
  await flag.click({ force: true });
  await expect(sheet).toBeVisible({ timeout: 3000 });
  expect(Date.now() - started).toBeLessThan(3000);
});
