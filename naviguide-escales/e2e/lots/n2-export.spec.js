// Exporter GeoJSON / KML de la route de la vue.
// Sans API : route.geojson + boutons + téléchargement tiennent seuls.
// GET /voyage/official : sondé ; rien n'en dépend ici (jamais affaibli).
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (name) => join(here, "../../../docs/recette/lot-n1", name);

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-n2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showToolsPanel(page) {
  const box = page.getByTestId("export-box");
  if (await box.isVisible().catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect(box).toBeVisible({ timeout: 10_000 });
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

async function enterDraw(page) {
  const { enterTracer } = await import("../helpers.js");
  await enterTracer(page);
}

async function readDownload(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

test("Exporter GeoJSON et KML : fichier non vide ; Tracer = route dessinée", async ({ page }) => {
  test.setTimeout(45_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — export servi par route.geojson / dessin (jamais affaibli)",
    });
  }

  page.on("dialog", (d) => d.accept());
  await stubRoute(page);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 30_000 });

  await showToolsPanel(page);
  await expect(page.getByTestId("export-box")).toBeVisible();
  await expect(page.getByTestId("export-box")).toContainText(/Exporter|Export/);
  const geoBtn = page.getByTestId("export-geojson");
  const kmlBtn = page.getByTestId("export-kml");
  await expect(geoBtn).toBeVisible();
  await expect(kmlBtn).toBeVisible();
  await expect(geoBtn).toHaveText("GeoJSON");
  await expect(kmlBtn).toHaveText("KML");
  await expect(geoBtn).toBeEnabled({ timeout: 30_000 });
  await expect(kmlBtn).toBeEnabled();
  await expect(page.getByTestId("escale-legend")).toBeVisible({ timeout: 30_000 });

  const [geoDownload] = await Promise.all([
    page.waitForEvent("download"),
    geoBtn.click(),
  ]);
  expect(geoDownload.suggestedFilename()).toMatch(/^naviguide-(suivre|simulation)-\d{4}-\d{2}-\d{2}\.geojson$/);
  const geoText = await readDownload(geoDownload);
  expect(geoText.length).toBeGreaterThan(0);
  const geo = JSON.parse(geoText);
  expect(geo.type).toBe("FeatureCollection");
  expect(geo.features.length).toBeGreaterThan(0);
  expect(geo.features.some((f) => f.geometry?.type === "LineString")).toBeTruthy();
  expect(geo.features.some((f) => f.geometry?.type === "Point")).toBeTruthy();

  const [kmlDownload] = await Promise.all([
    page.waitForEvent("download"),
    kmlBtn.click(),
  ]);
  expect(kmlDownload.suggestedFilename()).toMatch(/^naviguide-(suivre|simulation)-\d{4}-\d{2}-\d{2}\.kml$/);
  const kmlText = await readDownload(kmlDownload);
  expect(kmlText.length).toBeGreaterThan(0);
  expect(kmlText).toMatch(/<kml[\s>]/);
  expect(kmlText).toContain("<LineString>");
  expect(kmlText).toContain("<Point>");

  await shot(page, "01-export");

  await enterDraw(page);
  await page.getByTestId("route-import-file").setInputFiles(fixture("trois-points.geojson"));
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 3, { timeout: 15_000 });
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 2, { timeout: 20_000 });

  await showToolsPanel(page);
  await expect(page.getByTestId("export-geojson")).toBeEnabled();
  const [drawnDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("export-geojson").click(),
  ]);
  expect(drawnDownload.suggestedFilename()).toMatch(/^naviguide-tracer-\d{4}-\d{2}-\d{2}\.geojson$/);
  const drawnText = await readDownload(drawnDownload);
  expect(drawnText.length).toBeGreaterThan(0);
  const drawn = JSON.parse(drawnText);
  expect(drawn.type).toBe("FeatureCollection");
  const names = drawn.features
    .filter((f) => f.geometry?.type === "Point")
    .map((f) => f.properties?.name);
  expect(names).toContain("La Rochelle");
  expect(names).toContain("Gijon");
  expect(names).toContain("Lisbonne");
  expect(drawn.features.filter((f) => f.geometry?.type === "LineString").length).toBeGreaterThanOrEqual(2);
});
