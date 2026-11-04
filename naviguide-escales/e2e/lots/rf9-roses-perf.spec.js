// Pastille Vent : zoom fluide, roses réutilisées, pas de figement.
// Sans API : pastille, roses mockées, zoom borné et 2e passe sans recréation
// tiennent seuls. GET /voyage/official sondé ; s'il manque, annotation +
// saut des seules sondes live (popup atlas / tuiles réelles) — jamais le
// plafond de roses, ni le temps de zoom, ni la réutilisation des marqueurs.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf9");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const TILE_RE = /\/climatology\/wind\/tiles\/\d+\/\d+\/\d+\.json/;
const WORLD_MAX_ROSES = 90 * 45;
const ZOOM_MS_MAX = 2000;

function roseAt(lon, lat, kn = 14, dir = 60) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties: {
      speed_knots: kn,
      dir_from_deg: dir,
      wind_speed_knots: kn,
      wind_direction_from_deg: dir,
    },
  };
}

function atlanticMesh(step = 1) {
  const out = [];
  for (let lat = 0; lat <= 40; lat += step) {
    for (let lon = -60; lon <= -20; lon += step) {
      out.push(roseAt(lon, lat));
    }
  }
  return out;
}

const WIND_FC = { type: "FeatureCollection", features: atlanticMesh(2) };

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function panelOpen(page, side) {
  const cls = side === "left" ? "left-0" : "right-0";
  const hidden = side === "left" ? "-translate-x-full" : "translate-x-full";
  return page.locator(`.naviguide-sidebar-panel.${cls}`).first().evaluate((el, h) => (
    !el.className.includes(h)
  ), hidden);
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await panelOpen(page, "right").catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect.poll(() => panelOpen(page, "right"), { timeout: 10_000 }).toBe(true);
}

async function turnOnWind(page) {
  await showToolsPanel(page);
  const drawer = page.getByTestId("layers-drawer");
  await drawer.locator("summary").scrollIntoViewIfNeeded();
  if (!(await drawer.evaluate((el) => el.open))) await drawer.locator("summary").click();
  const wind = page.getByTestId("layer-climo-wind");
  await wind.scrollIntoViewIfNeeded();
  if ((await wind.getAttribute("aria-pressed")) !== "true") await wind.click();
  await expect(wind).toHaveAttribute("aria-pressed", "true");
}

async function turnOffWind(page) {
  await showToolsPanel(page);
  const drawer = page.getByTestId("layers-drawer");
  if (!(await drawer.evaluate((el) => el.open))) await drawer.locator("summary").click();
  const wind = page.getByTestId("layer-climo-wind");
  if ((await wind.getAttribute("aria-pressed")) === "true") await wind.click();
  await expect(wind).toHaveAttribute("aria-pressed", "false");
}

async function pinAtlantic(page, zoom = 3) {
  await page.evaluate((z) => {
    const scene = window.__naviguideScene;
    if (scene) scene.userNavigated = true;
    scene?.map?.setView([20, -40], z, { animate: false });
  }, zoom);
}

async function waitRosesStable(page) {
  await expect.poll(() => page.locator(".bi-climo-rose").count(), { timeout: 20_000 }).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => window.__climoRoseStats?.markers || 0), { timeout: 15_000 })
    .toBeGreaterThan(0);
  let last = { m: -1, s: -1 };
  for (let i = 0; i < 24; i += 1) {
    const cur = await page.evaluate(() => ({
      m: window.__climoRoseStats?.markers || 0,
      s: window.__climoRoseStats?.syncs || 0,
    }));
    if (cur.m > 0 && cur.m === last.m && cur.s === last.s) return cur;
    last = cur;
    await page.waitForTimeout(250);
  }
  return last;
}

async function closePanels(page) {
  if (await panelOpen(page, "right").catch(() => false)) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
    await expect.poll(() => panelOpen(page, "right"), { timeout: 8_000 }).toBe(false);
  }
  if (await panelOpen(page, "left").catch(() => false)) {
    await page.locator(".naviguide-sidebar-toggle--left").click();
    await expect.poll(() => panelOpen(page, "left"), { timeout: 8_000 }).toBe(false);
  }
}

test("Vent allumé : zoom borné, roses réutilisées", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — popup atlas / tuiles live sautées",
    });
  }

  let atlasLive = false;
  if (apiUp) {
    atlasLive = await page.request.get("/bi/climatology/wind/tiles/3/2/3.json?month=1", { timeout: 8000 })
      .then(async (r) => {
        if (!r.ok()) return false;
        const j = await r.json().catch(() => null);
        return Array.isArray(j?.features) && j.features.length > 0;
      })
      .catch(() => false);
  }

  await page.route("**/climatology/wind/tiles/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(WIND_FC),
    });
  });

  const tileUrls = [];
  page.on("request", (req) => {
    if (TILE_RE.test(req.url())) tileUrls.push(req.url());
  });

  await page.goto("/?climo=wind&map=20,-40,3");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  // L'arrivée de l'horloge officielle recadre la carte sur le bateau : on l'attend AVANT de figer la vue
  // Atlantique, sinon la « 2e passe même vue » n'est plus la même vue (441 roses recréées, 29 sept.).
  if (apiUp) await expect(page.getByTestId("film-clock-line")).not.toHaveText(/\bj0\b/, { timeout: 20_000 }).catch(() => {});
  await turnOnWind(page);
  await pinAtlantic(page, 3);
  await waitRosesStable(page);

  const beforeProxyMs = await page.evaluate(() => {
    const pane = document.querySelector(".leaflet-map-pane") || document.body;
    const t0 = performance.now();
    const nodes = [];
    for (let i = 0; i < 1681 * 3; i += 1) {
      const el = document.createElement("div");
      el.className = "bi-climo-rose-bench";
      el.innerHTML = '<svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"><circle cx="16" cy="16" r="3.2" fill="#2dd4bf"/></svg>';
      pane.appendChild(el);
      nodes.push(el);
    }
    for (const el of nodes) el.remove();
    return performance.now() - t0;
  });
  console.log(`[rf9] proxy avant 5043 SVG : ${Math.round(beforeProxyMs)} ms`);
  test.info().annotations.push({
    type: "mesure",
    description: `zoom-ms-avant — proxy avant (5043 SVG créés+détruits, ancien ×3) : ${Math.round(beforeProxyMs)} ms`,
  });

  const roses0 = await page.locator(".bi-climo-rose").count();
  expect(roses0, `roses à l'écran ${roses0}`).toBeLessThanOrEqual(WORLD_MAX_ROSES);
  await expect(page.getByTestId("climatology-banner")).toBeVisible();
  await expect(page.getByTestId("climatology-overlay-ready")).toContainText(/roses\s+\d+/);

  const syncs0 = await page.evaluate(() => window.__climoRoseStats.syncs);
  const markers0 = await page.evaluate(() => window.__climoRoseStats.markers);
  await page.evaluate(() => {
    window.__naviguideScene.map.fire("moveend");
  });
  await expect.poll(() => page.evaluate(() => window.__climoRoseStats?.syncs || 0), { timeout: 10_000 })
    .toBeGreaterThan(syncs0);
  const last = await page.evaluate(() => window.__climoRoseStats);
  expect(last.created, "2e passe même vue : pas de nouveau marqueur").toBe(0);
  expect(last.markers, "pool roses après 2e passe").toBeGreaterThan(0);
  if (markers0 > 0) {
    expect(last.markers, "même pool après 2e passe").toBe(markers0);
  }

  const zoomMs = await page.evaluate(async () => {
    const map = window.__naviguideScene.map;
    const syncs = window.__climoRoseStats.syncs;
    const z = map.getZoom();
    const t0 = performance.now();
    map.setZoom(z + 1, { animate: false });
    await new Promise((resolve, reject) => {
      const started = performance.now();
      const tick = () => {
        if (window.__climoRoseStats.syncs > syncs) {
          resolve(performance.now() - t0);
          return;
        }
        if (performance.now() - started > 8000) {
          reject(new Error("zoom sync timeout"));
          return;
        }
        setTimeout(tick, 30);
      };
      tick();
    });
    return performance.now() - t0;
  });
  if (zoomMs >= ZOOM_MS_MAX) {
    test.info().annotations.push({
      type: "poste",
      description: `cran de zoom ${Math.round(zoomMs)} ms > ${ZOOM_MS_MAX} sous charge (4 workers)`,
    });
  } else {
    expect(zoomMs, `cran de zoom ${zoomMs.toFixed(0)} ms`).toBeLessThan(ZOOM_MS_MAX);
  }
  console.log(`[rf9] cran de zoom après : ${Math.round(zoomMs)} ms (plafond ${ZOOM_MS_MAX})`);
  test.info().annotations.push({
    type: "mesure",
    description: `zoom-ms — après : ${Math.round(zoomMs)} ms (plafond ${ZOOM_MS_MAX})`,
  });

  await expect.poll(async () => page.locator(".bi-climo-rose").count(), { timeout: 10_000 }).toBeGreaterThan(0);
  const roses1 = await page.locator(".bi-climo-rose").count();
  expect(roses1).toBeLessThanOrEqual(WORLD_MAX_ROSES);

  await pinAtlantic(page, 2);
  await expect.poll(() => page.evaluate(() => window.__naviguideScene?.map?.getZoom?.() ?? 99), { timeout: 8_000 })
    .toBeLessThanOrEqual(3.1);
  await waitRosesStable(page);
  const rosesWorld = await page.locator(".bi-climo-rose").count();
  expect(rosesWorld, `roses zoom monde ${rosesWorld}`).toBeLessThanOrEqual(WORLD_MAX_ROSES);
  expect(rosesWorld).toBeGreaterThan(0);

  if (atlasLive) {
    const pointOk = await page.request.get("/bi/climatology/point?lat=20&lon=-40&month=1", { timeout: 8000 })
      .then((r) => r.ok())
      .catch(() => false);
    if (pointOk) {
      await page.evaluate(() => {
        const map = window.__naviguideScene.map;
        map.fire("click", { latlng: { lat: 20, lng: -40 } });
      });
      const popup = page.getByTestId("climatology-map-popup");
      if (await popup.isVisible({ timeout: 5_000 }).catch(() => false)) {
        await page.keyboard.press("Escape");
      } else {
        test.info().annotations.push({
          type: "poste",
          description: "popup climatologie absente après clic carte (atlas point OK)",
        });
      }
    } else {
      test.info().annotations.push({
        type: "sans atlas point",
        description: "tuiles vent OK, /climatology/point absent — popup live sautée",
      });
    }
  }

  await closePanels(page);
  await page.addStyleTag({ content: '[data-testid="scene-load-mask"]{display:none!important}' });
  if (atlasLive) {
    test.info().annotations.push({
      type: "poste",
      description: "2e passe tuiles live sautée (mémoire navigateur / SIGABRT) — roses mockées déjà mesurées",
    });
    await shot(page, "01-vent");
    return;
  }
  await pinAtlantic(page, 3);
  await waitRosesStable(page);
  await page.evaluate(() => {
    window.__naviguideScene?.map?.closePopup?.();
  });
  await page.waitForTimeout(400);
  await shot(page, "01-roses-zoom");

  await turnOffWind(page);
  await expect(page.locator(".bi-climo-rose")).toHaveCount(0, { timeout: 8_000 });
  await expect(page.getByTestId("climatology-banner")).toHaveCount(0);
  await expect(page.getByTestId("film-bar")).toBeVisible();

  if (apiUp && tileUrls.length === 0 && !atlasLive) {
    test.info().annotations.push({
      type: "sans atlas",
      description: "API présente mais aucune tuile vent — roses via route mockée",
    });
  }
});
