// Importer GeoJSON / KML dans Tracer ma route.
// Sans API : parseur + drapeaux + corde /route tiennent seuls.
// GET /voyage/official : sondé ; le sac après Terminer n'est vérifié
// que s'il répond (jamais affaibli sinon).
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (name) => join(here, "../../../docs/recette/lot-n1", name);

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-n1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

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

async function enterDraw(page) {
  const { enterTracer } = await import("../helpers.js");
  await enterTracer(page);
  await expect(page.getByTestId("route-import")).toBeVisible();
}

async function importFile(page, name) {
  await page.getByTestId("route-import-file").setInputFiles(fixture(name));
}

test("Importer un .geojson puis un .kml : 3 drapeaux, route, Terminer", async ({ page }) => {
  test.setTimeout(45_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — sac après Terminer non exigé",
    });
  }

  page.on("dialog", (d) => d.accept());
  await stubRoute(page);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 30_000 });

  await enterDraw(page);
  await expect(page.getByRole("button", { name: /^(importer|import)$/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /terminer|finish/i })).toBeVisible();

  await importFile(page, "trois-points.geojson");
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 3, { timeout: 15_000 });
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 2, { timeout: 20_000 });
  const list = page.getByTestId("drawing-points").locator("li");
  await expect(list).toHaveCount(3);
  await expect(page.getByTestId("drawing-points")).toContainText("La Rochelle");
  await expect(page.getByTestId("drawing-points")).toContainText("Gijon");
  await expect(page.getByTestId("drawing-points")).toContainText("Lisbonne");
  await expect(page.getByTestId("waypoint-flag").first()).toBeVisible({ timeout: 10_000 });
  await shot(page, "01-import");

  const before = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
  await page.getByTestId("route-import-file").setInputFiles({
    name: "vide.geojson",
    mimeType: "application/geo+json",
    buffer: Buffer.from("{"),
  });
  await expect(page.getByTestId("route-import-error")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("route-import-error")).toContainText(/Fichier illisible|Unreadable file/);
  const afterBad = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
  expect(afterBad).toEqual(before);

  await importFile(page, "trois-points.kml");
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 3, { timeout: 15_000 });
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 2, { timeout: 20_000 });
  await expect(page.getByTestId("drawing-points").locator("li")).toHaveCount(3);
  await expect(page.getByTestId("drawing-points")).toContainText("La Rochelle");
  await shot(page, "02-import-kml");

  const finish = page.getByRole("button", { name: /terminer|finish/i });
  if (!(await finish.isVisible().catch(() => false))) {
    await page.locator(".naviguide-sidebar-toggle--left").click();
  }
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  await expect(page.getByTestId("drawing-points")).toHaveCount(0);

  if (apiUp) {
    const briefing = page.getByTestId("briefing");
    await expect(briefing).toBeVisible({ timeout: 20_000 });
    await expect(briefing).not.toContainText(/Bourgenay/i, { timeout: 20_000 });
  }
});
