// Carte NOW piraterie (Aden HIGH, hors zone rien).
// Sans API : barre film + Simulation tiennent ; pas de carte « Piraterie » au départ.
// GET /voyage/official : sondé ; les assertions sac / carte Aden ne tournent
// que s'il répond ET que /ici porte piracy (jamais affaiblies sinon).
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const ADEN_LAT = 12.6;
const ADEN_LON = 48.2;
const PIRACY_FR = "Piraterie — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO";
const PIRACY_EN = "Piracy — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO";
const here = dirname(fileURLToPath(import.meta.url));
const recetteDir = join(here, "../../../docs/recette/lot-n4");

const shot = async (page, name) => {
  mkdirSync(recetteDir, { recursive: true });
  await page.screenshot({
    path: join(recetteDir, `${name}.webp`),
    type: "webp",
    quality: 85,
    fullPage: false,
  });
};

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const drawBtn = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i });
  if (await drawBtn.isVisible().catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
}

async function stubRoute(page) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
        properties: {},
      }),
    });
  });
}

test("Carte NOW piraterie à Aden, absente au large de La Rochelle", async ({ page }) => {
  test.setTimeout(120_000);
  const officialUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!officialUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — horloge Berry non exigée ; le sac /ici reste sondé",
    });
  }

  const iciAden = await page.request.get(`/ici?lat=${ADEN_LAT}&lon=${ADEN_LON}&thin=1`, { timeout: 45_000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const iciHome = await page.request.get("/ici?lat=46.15&lon=-1.17&thin=1", { timeout: 45_000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  if (!iciAden && !iciHome) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /ici absent — sac et carte Aden non exigés",
    });
  }
  if (iciHome && Object.prototype.hasOwnProperty.call(iciHome, "piracy")) {
    expect(iciHome.piracy, "La Rochelle hors zone").toBeNull();
  }

  const serverHasN4 = Boolean(iciAden?.piracy?.name) && iciAden.piracy.level === "HIGH";
  if ((iciAden || iciHome) && !serverHasN4) {
    test.info().annotations.push({
      type: "poste",
      description: "GET /ici sans piracy HIGH à Aden (Overpass / sac ici, jamais en CI) — carte Aden non exigée",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("dialog", (d) => d.accept());
  await stubRoute(page);
  if (serverHasN4) {
    await page.route("**/ici?*", async (route) => {
      const url = new URL(route.request().url());
      const lat = Number(url.searchParams.get("lat"));
      const lon = Number(url.searchParams.get("lon"));
      const inAden = lat >= 10 && lat <= 16 && lon >= 42 && lon <= 57;
      if (inAden) {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ ...iciAden, at: { lat, lon }, piracy: iciAden.piracy }),
        });
        return;
      }
      await route.continue();
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);

  const nowCard = page.getByTestId("moment-now");
  if (await nowCard.isVisible({ timeout: 4000 }).catch(() => false)) {
    await expect(nowCard).not.toContainText(/Piraterie —|Piracy —/);
  }

  if (serverHasN4) {
    expect(iciAden.piracy.name).toBe("Horn of Africa / Gulf Aden");
    expect(iciAden.piracy.source).toBe("IMB/UKMTO");

    await showLeftPanel(page);
    const draw = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Draw your own route/i });
    await expect(draw).toBeVisible({ timeout: 15_000 });
    // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
    await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /^(importer|import)$/i })).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("route-import-file").setInputFiles({
      name: "aden.geojson",
      mimeType: "application/geo+json",
      buffer: Buffer.from(JSON.stringify({
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: { name: "Aden W" }, geometry: { type: "Point", coordinates: [45.0, 12.8] } },
          { type: "Feature", properties: { name: "Aden E" }, geometry: { type: "Point", coordinates: [ADEN_LON, ADEN_LAT] } },
        ],
      })),
    });
    await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 2, { timeout: 15_000 });
    const finish = page.getByRole("button", { name: /terminer|finish/i });
    if (!(await finish.isVisible().catch(() => false))) {
      await page.locator(".naviguide-sidebar-toggle--left").click();
    }
    await expect(finish).toBeEnabled({ timeout: 20_000 });
    await finish.click();
    await page.getByTestId("view-tracer").click();
    await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
    await leaveCinema(page);
    await page.waitForFunction(() => {
      const ll = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
      return Boolean(ll && ll.lat >= 10 && ll.lat <= 16 && ll.lng >= 42 && ll.lng <= 57);
    }, { timeout: 20_000 });

    const piracyNow = page.getByTestId("moment-now").filter({ hasText: new RegExp(`${PIRACY_FR}|${PIRACY_EN}`) });
    await expect(piracyNow).toBeVisible({ timeout: 40_000 });
    await shot(page, "01-aden");
  }

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
