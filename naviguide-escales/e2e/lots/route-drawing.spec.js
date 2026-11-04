// Tracé : 3 points → 2 jambes, distance = somme des /route, pas de segment à terre,
// poursuite après Terminer, plafond de 60 points, aller-retour GeoJSON.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer, showLeftPanel, showRightPanel } from "../helpers.js";

const LA_ROCHELLE = { lat: 46.157, lon: -1.151, name: "La Rochelle" };
const GIJON = { lat: 43.545, lon: -5.662, name: "Gijon" };
const LISBON = { lat: 38.722, lon: -9.139, name: "Lisbonne" };
const PARIS = { lat: 48.8566, lon: 2.3522 };
const LEG_KM = 185.2;

function isInland(lat, lon) {
  return lat > 47 && lon > 0;
}

async function stubRoute(page, lengths) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    if (!Number.isFinite(slat) || slat > 90 || slat < -90 || slon > 180 || slon < -180) {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "out_of_range" }),
      });
      return;
    }
    if (isInland(slat, slon) || isInland(elat, elon)) {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "on_land" }),
      });
      return;
    }
    const samePoint = Math.abs(slat - elat) < 1e-4 && Math.abs(slon - elon) < 1e-4;
    if (!samePoint) lengths.push(LEG_KM);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
        properties: { length: LEG_KM, units: "km" },
      }),
    });
  });
}

async function addNamed(page, point) {
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon, { name: p.name }), point);
}

test("3 points, 2 jambes mer, distance des /route, suite et GeoJSON", async ({ page }) => {
  test.setTimeout(90_000);
  const lengths = [];
  await stubRoute(page, lengths);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await expect(page.getByTestId("draw-point-limit")).toContainText("60 points maximum");

  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  await addNamed(page, LA_ROCHELLE);
  await addNamed(page, GIJON);
  await addNamed(page, LISBON);
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) === 2, { timeout: 20_000 });

  const drawn = await page.evaluate(() => window.__naviguideDrawn);
  expect(drawn.points).toHaveLength(3);
  expect(drawn.segments).toHaveLength(2);
  expect(drawn.segments.every((seg) => seg.failed !== true)).toBe(true);
  expect(drawn.points.map((p) => p.name)).toEqual(["La Rochelle", "Gijon", "Lisbonne"]);

  const legNm = lengths.reduce((sum, km) => sum + km / 1.852, 0);
  const shown = await page.getByTestId("drawing-points").innerText();
  const match = shown.match(/([\d\s\u00a0\u202f]+)\s*nm/i);
  expect(match, shown).toBeTruthy();
  const displayed = Number(String(match[1]).replace(/[^\d]/g, ""));
  expect(Math.abs(displayed - legNm) / legNm).toBeLessThan(0.01);

  const beforeLand = drawn.points.length;
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), PARIS);
  await expect(page.getByTestId("route-import-error")).toContainText(/terre|land/i, { timeout: 8_000 });
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(beforeLand);

  await showRightPanel(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("export-geojson").click(),
  ]);
  const raw = (await import("node:fs")).readFileSync(await download.path(), "utf8");
  const geo = JSON.parse(raw);
  const exportedPoints = geo.features
    .filter((f) => f.geometry?.type === "Point")
    .map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
  const live = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
  expect(exportedPoints).toEqual(live);

  page.on("dialog", (dialog) => dialog.accept());
  await showLeftPanel(page);
  await page.locator(".naviguide-sidebar-panel.left-0").getByRole("button", { name: /^(annuler|cancel)$/i }).click();
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 0);
  await page.getByTestId("route-import-file").setInputFiles({
    name: "roundtrip.geojson",
    mimeType: "application/geo+json",
    buffer: Buffer.from(raw),
  });
  await page.waitForFunction((n) => (window.__naviguideDrawn?.points?.length || 0) === n, live.length, { timeout: 20_000 });
  const again = await page.evaluate(() => (window.__naviguideDrawn?.points || []).map((p) => [p.lat, p.lon]));
  expect(again.map((p) => [Number(p[0].toFixed(5)), Number(p[1].toFixed(5))])).toEqual(
    live.map((p) => [Number(p[0].toFixed(5)), Number(p[1].toFixed(5))]),
  );

  await showLeftPanel(page);
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 15_000 });
  await finish.click();
  const continueBtn = page.getByRole("button", { name: /Continuer le tracé|Continue drawing/i });
  await expect(continueBtn).toBeVisible({ timeout: 10_000 });
  await continueBtn.click();
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 10_000 });
  await page.evaluate(() => window.__naviguideAddDrawnPoint(36.5, -6.3, { name: "Au large" }));
  await page.waitForFunction((n) => (window.__naviguideDrawn?.points?.length || 0) === n, live.length + 1, { timeout: 15_000 });
  await page.waitForFunction((n) => (window.__naviguideDrawn?.segments?.length || 0) === n, live.length, { timeout: 15_000 });
});

test("le 61e point est refusé", async ({ page }) => {
  test.setTimeout(90_000);
  await stubRoute(page, []);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  await page.evaluate(async () => {
    for (let i = 0; i < 61; i += 1) {
      await window.__naviguideAddDrawnPoint(44 - i * 0.02, -3 - i * 0.02);
    }
  });
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), {
    timeout: 20_000,
  }).toBe(60);
  await expect(page.getByTestId("draw-point-limit")).toContainText("60 points maximum");
});
