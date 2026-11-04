// Après Terminer, le briefing raconte le sac de la route dessinée.
// Sans API : pas de « Bourgenay » (la route officielle ne fuit pas).
// Avec API (proxy /ici → :8010) : le briefing cite la Mauritanie.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-t/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

// Au large de Nouadhibou, hors de tout WPI vendéen.
const MAURITANIE_A = { lat: 18.2, lon: -17.8 };
const MAURITANIE_B = { lat: 17.6, lon: -16.9 };

async function clickLatLng(page, lat, lon) {
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => {
    window.__naviguideAddDrawnPoint(lat, lon);
  }, { lat, lon });
}

async function apiAlive(page) {
  return page.evaluate(async () => {
    const ctrl = new AbortController();
    const kill = setTimeout(() => ctrl.abort(), 4000);
    try {
      const r = await fetch("/ici?lat=18.2&lon=-17.8&thin=1", { signal: ctrl.signal });
      return r.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(kill);
    }
  });
}

test("Route dessinée au large de la Mauritanie : pas de Bourgenay", async ({ page }) => {
  test.setTimeout(120_000);
  // Le proxy preview → :8010 a laissé /route en vol (Terminer reste disabled).
  // La corde suffit : le lot T recette le sac, pas searoute.
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

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 30_000 });

  const { enterTracer } = await import("../helpers.js");
  await enterTracer(page);

  const tools = page.getByTestId("drawing-summary");
  if (!(await tools.isVisible().catch(() => false))) {
    await page.locator(".naviguide-sidebar-toggle--right").click();
  }

  await clickLatLng(page, MAURITANIE_A.lat, MAURITANIE_A.lon);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await clickLatLng(page, MAURITANIE_B.lat, MAURITANIE_B.lon);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 1, { timeout: 20_000 });

  const finish = page.getByRole("button", { name: /terminer/i });
  await openLeftDrawer(page);
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();

  const briefing = page.getByTestId("briefing");
  await expect(briefing).toBeVisible({ timeout: 20_000 });
  await expect(briefing).not.toContainText(/Bourgenay/i, { timeout: 20_000 });

  if (await apiAlive(page)) {
    await expect(briefing).toContainText(/Mauritanie|Mauritania/i, { timeout: 45_000 });
  }

  await page.evaluate(({ a, b }) => {
    const map = window.__naviguideScene?.map;
    if (!map) return;
    map.fitBounds([[a.lat, a.lon], [b.lat, b.lon]], {
      animate: false,
      padding: [56, 56],
      maxZoom: 5,
    });
  }, { a: MAURITANIE_A, b: MAURITANIE_B });
  await page.waitForTimeout(600);
  await shot(page, "01-mauritanie");
});
