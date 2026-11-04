// Un point refusé se dit : point sur terre, limite de 60 points (tracé et
// import). Le message est visible, au-dessus de la carte et des panneaux.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer, showLeftPanel } from "../helpers.js";

const PARIS = { lat: 48.8566, lon: 2.3522 };

async function stubRoute(page) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    if (elat > 47 && elon > 0) {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "on_land" }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
        properties: { length: 10, units: "km" },
      }),
    });
  });
}

/** Visible pour de vrai : le centre du message n'est couvert par rien. */
async function expectOnTop(page, locator) {
  await expect(locator).toBeVisible({ timeout: 8_000 });
  const onTop = await locator.evaluate((el) => {
    // Le message ne capte pas les clics (pointer-events: none) : on le rend
    // « touchable » le temps du test pour savoir si quelque chose le couvre.
    el.style.pointerEvents = "auto";
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return Boolean(hit && (hit === el || el.contains(hit)));
  });
  expect(onTop).toBe(true);
}

async function open(page, lang) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
}

for (const [lang, onLand, limit] of [
  ["fr", "Point sur terre : non ajouté", "Limite de 60 points atteinte"],
  ["en", "Point on land: not added", "60-point limit reached"],
]) {
  test(`${lang} : un point sur terre refusé affiche un message visible`, async ({ page }) => {
    test.setTimeout(90_000);
    await open(page, lang);
    await page.evaluate(() => window.__naviguideAddDrawnPoint(46.0, -2.5));
    await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1);
    await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), PARIS);
    const notice = page.getByTestId("route-import-error");
    await expect(notice).toHaveText(onLand, { timeout: 8_000 });
    await expectOnTop(page, notice);
    await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(1);
  });

  test(`${lang} : la limite de 60 points se dit au tracé`, async ({ page }) => {
    test.setTimeout(120_000);
    await open(page, lang);
    await page.evaluate(async () => {
      for (let i = 0; i < 61; i += 1) await window.__naviguideAddDrawnPoint(44 - i * 0.02, -3 - i * 0.02);
    });
    await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), { timeout: 20_000 }).toBe(60);
    const notice = page.getByTestId("route-import-notice");
    await expect(notice).toHaveText(limit, { timeout: 8_000 });
    await expectOnTop(page, notice);
  });
}

test("import de plus de 60 points : message visible", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page, "fr");
  const features = Array.from({ length: 65 }, (_, i) => ({
    type: "Feature",
    properties: { name: `P${i + 1}` },
    geometry: { type: "Point", coordinates: [-3 - i * 0.02, 44 - i * 0.02] },
  }));
  await showLeftPanel(page);
  await page.getByTestId("route-import-file").setInputFiles({
    name: "long.geojson",
    mimeType: "application/geo+json",
    buffer: Buffer.from(JSON.stringify({ type: "FeatureCollection", features })),
  });
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), { timeout: 30_000 }).toBe(60);
  const notice = page.getByTestId("route-import-notice");
  await expect(notice).toContainText("60 points maximum", { timeout: 8_000 });
  await expectOnTop(page, notice);
});

test("390 px : le message de point sur terre reste visible", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "fr");
  await page.evaluate(() => window.__naviguideAddDrawnPoint(46.0, -2.5));
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), PARIS);
  const notice = page.getByTestId("route-import-error");
  await expect(notice).toHaveText("Point sur terre : non ajouté", { timeout: 8_000 });
  await expectOnTop(page, notice);
  const box = await notice.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
});
