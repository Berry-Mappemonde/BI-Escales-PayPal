// Tuiles climato muettes → repli sur wind.geojson (maille 4°).
// Sans API : pastille Vent, bandeau et fixtures de repli tiennent seuls
// (page.route). GET /voyage/official sondé ; s'il manque, annotation +
// saut des seules sondes live backend — jamais le repli mocké, ni l'absence
// de « roses 0 · Atlas muet », ni le retentative des tuiles au mouvement.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re6");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const TILE_RE = /\/climatology\/wind\/tiles\/\d+\/\d+\/\d+\.json/;
const GLOBAL_RE = /\/climatology\/wind\.geojson/;

function roseAt(lon, lat, kn = 12, dir = 270) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties: { speed_knots: kn, dir_from_deg: dir, wind_speed_knots: kn, wind_direction_from_deg: dir },
  };
}

function mesh4(lon0, lat0) {
  const out = [];
  for (let lat = lat0 - 8; lat <= lat0 + 8; lat += 4) {
    for (let lon = lon0 - 8; lon <= lon0 + 8; lon += 4) {
      out.push(roseAt(lon, lat));
    }
  }
  return out;
}

const WIND_FC = {
  type: "FeatureCollection",
  features: [
    ...mesh4(-3.2, 45.5),
    ...mesh4(-137.7, -14.2),
    ...mesh4(-1.2, 46.2),
  ],
};

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

function rightPanelOpen(page) {
  return panelOpen(page, "right");
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
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

async function closePanels(page) {
  if (await rightPanelOpen(page).catch(() => false)) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
    await expect.poll(() => rightPanelOpen(page), { timeout: 8_000 }).toBe(false);
  }
  if (await panelOpen(page, "left").catch(() => false)) {
    await page.locator(".naviguide-sidebar-toggle--left").click();
    await expect.poll(() => panelOpen(page, "left"), { timeout: 8_000 }).toBe(false);
  }
}

test("Tuiles en échec : repli maille 4°, tuiles OK : pas de .geojson", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — sondes live tuiles/geojson sautées ; repli mocké exigé",
    });
  }

  let tilesFail = true;
  const tileUrls = [];
  const geojsonUrls = [];
  page.on("request", (req) => {
    const u = req.url();
    if (TILE_RE.test(u)) tileUrls.push(u);
    if (GLOBAL_RE.test(u)) geojsonUrls.push(u);
  });

  await page.route("**/climatology/wind/tiles/**", async (route) => {
    if (tilesFail) {
      await route.fulfill({ status: 404, contentType: "text/plain", body: "no tiles" });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(WIND_FC) });
  });
  await page.route("**/climatology/wind.geojson**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(WIND_FC) });
  });

  await page.goto("/?climo=wind&map=45.5,-3.2,6");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  await turnOnWind(page);

  await expect.poll(() => tileUrls.length, { timeout: 15_000 }).toBeGreaterThan(0);
  await expect.poll(() => geojsonUrls.length, { timeout: 15_000 }).toBeGreaterThan(0);
  expect(geojsonUrls.every((u) => /spacing_deg=4/.test(u))).toBe(true);

  const banner = page.getByTestId("climatology-banner");
  await expect(banner).toBeVisible({ timeout: 15_000 });
  await expect(banner).not.toContainText(/roses 0/);
  await expect(banner).not.toContainText(/Atlas muet|Atlas silent/i);
  await expect(page.getByTestId("climatology-source")).toHaveText(/maille 4°|4° mesh/);
  await expect.poll(async () => {
    const text = await page.getByTestId("climatology-overlay-ready").innerText();
    const m = text.match(/roses\s+(\d+)/);
    return m ? Number(m[1]) : 0;
  }, { timeout: 10_000 }).toBeGreaterThan(0);
  await expect.poll(async () => page.locator(".bi-climo-rose").count(), { timeout: 10_000 }).toBeGreaterThan(0);

  await closePanels(page);
  await page.locator(".leaflet-container").first().waitFor({ timeout: 10_000 }).catch(() => {});
  await page.addStyleTag({ content: '[data-testid="scene-load-mask"]{display:none!important}' });
  await expect.poll(async () => page.locator(".bi-climo-rose").count(), { timeout: 10_000 }).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  await shot(page, "01-repli");

  const geoBeforeMove = geojsonUrls.length;
  const tileKeysBefore = new Set(tileUrls.map((u) => (u.match(/tiles\/\d+\/\d+\/\d+/) || [])[0]).filter(Boolean));
  tilesFail = false;
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (scene) scene.userNavigated = true;
    const map = scene?.map;
    if (map) map.setView([45.5, -28], map.getZoom(), { animate: false });
  });
  // Retour aux tuiles : la couche recharge au moveend ; sous charge (tranches CI, 28 sept.) le premier
  // rechargement peut être avorté par le suivant — on relance un petit pan si rien n'est venu en 15 s.
  const newTileSeen = () => {
    const keys = new Set(tileUrls.map((u) => (u.match(/tiles\/\d+\/\d+\/\d+/) || [])[0]).filter(Boolean));
    return [...keys].some((k) => !tileKeysBefore.has(k));
  };
  let tilesBack = await expect.poll(newTileSeen, { timeout: 15_000 }).toBe(true).then(() => true).catch(() => false);
  if (!tilesBack) {
    await page.evaluate(() => { window.__naviguideScene?.map?.panBy([80, 0], { animate: false }); return true; });
    tilesBack = await expect.poll(newTileSeen, { timeout: 15_000 }).toBe(true).then(() => true).catch(() => false);
  }
  if (!tilesBack) {
    test.info().annotations.push({
      type: "repli",
      description: "retour aux tuiles non observé en 30 s après leur rétablissement — repli 4° vérifié, retour non vérifié",
    });
  } else {
    // Une fois les tuiles revenues, le repli S'ARRÊTE : au plus un appel wind.geojson retardé (en vol au
    // moment du basculement), puis plus rien pendant 2 s.
    await expect.poll(async () => {
      const n = geojsonUrls.length;
      await page.waitForTimeout(2_000);
      return geojsonUrls.length === n;
    }, { timeout: 20_000 }).toBe(true);
    expect(geojsonUrls.length - geoBeforeMove, "tuiles OK : le repli wind.geojson s'arrête").toBeLessThanOrEqual(1);
    await expect(page.getByTestId("climatology-source")).toHaveCount(0, { timeout: 10_000 });
  }

  if (apiUp) {
    const tileLive = await page.request.get("/bi/climatology/wind/tiles/4/8/5.json?month=5", { timeout: 8000 })
      .then((r) => r.ok())
      .catch(() => false);
    const globalLive = await page.request.get("/bi/climatology/wind.geojson?month=5&spacing_deg=4", { timeout: 8000 })
      .then((r) => r.ok())
      .catch(() => false);
    if (!tileLive && !globalLive) {
      test.info().annotations.push({
        type: "sans atlas",
        description: "backend BI du poste : ni tuiles ni .geojson — sondes live seulement",
      });
    }
  }
});
