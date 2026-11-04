// A point refused because it is on land is removed wherever it is, and its
// neighbours are joined; a busy server says « try again » and keeps the point.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer } from "../helpers.js";

const A = { lat: 46.0, lon: -2.5 };
const B = { lat: 48.8566, lon: 2.3522 }; // Paris: on land
const C = { lat: 45.5, lon: -3.2 };
const onB = (lat, lon) => Math.abs(lat - B.lat) < 1e-6 && Math.abs(lon - B.lon) < 1e-6;

async function open(page, lang, handler) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await page.route("**/route?*", handler);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
}

function line(url) {
  const q = new URL(url).searchParams;
  const s = [Number(q.get("start_lon")), Number(q.get("start_lat"))];
  const e = [Number(q.get("end_lon")), Number(q.get("end_lat"))];
  return { s, e };
}

test("A (sea), B (land), C (sea) clicked fast: B goes, A–C is joined", async ({ page }) => {
  test.setTimeout(90_000);
  const asked = [];
  await open(page, "fr", async (route) => {
    const { s, e } = line(route.request().url());
    asked.push([s, e]);
    if (onB(s[1], s[0]) || onB(e[1], e[0])) {
      // Slow answer: C is already placed when it comes back.
      await new Promise((r) => setTimeout(r, 600));
      const end = onB(s[1], s[0]) ? "on_land_start" : "on_land_end";
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "on_land", end }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ type: "Feature", geometry: { type: "LineString", coordinates: [s, e] }, properties: { length: 120, units: "km" } }),
    });
  });
  await page.evaluate(({ A, B, C }) => {
    window.__naviguideAddDrawnPoint(A.lat, A.lon);
    window.__naviguideAddDrawnPoint(B.lat, B.lon);
    window.__naviguideAddDrawnPoint(C.lat, C.lon);
  }, { A, B, C });
  await expect(page.getByTestId("route-import-error")).toHaveText("Point sur terre : non ajouté", { timeout: 10_000 });
  await expect.poll(() => page.evaluate(() => {
    const d = window.__naviguideDrawn;
    return d ? { points: d.points.map((p) => [p.lat, p.lon]), legs: d.segments.length } : null;
  }), { timeout: 15_000 }).toEqual({ points: [[A.lat, A.lon], [C.lat, C.lon]], legs: 1 });
  const seg = await page.evaluate(() => window.__naviguideDrawn.segments[0]);
  expect([seg.from.lat, seg.to.lat]).toEqual([A.lat, C.lat]);
  expect(asked.some(([s, e]) => s[1] === A.lat && e[1] === C.lat)).toBe(true);
});

for (const [lang, text] of [["fr", "Serveur occupé, réessayez"], ["en", "Server busy, try again"]]) {
  test(`${lang}: a busy server says try again and keeps the point`, async ({ page }) => {
    test.setTimeout(90_000);
    await open(page, lang, async (route) => {
      const { s, e } = line(route.request().url());
      if (s[0] === e[0] && s[1] === e[1]) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ type: "Feature", geometry: { type: "LineString", coordinates: [s, e] }, properties: { length: 0, units: "km" } }) });
        return;
      }
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "busy" }) });
    });
    await page.evaluate(async ({ A, C }) => {
      await window.__naviguideAddDrawnPoint(A.lat, A.lon);
      await window.__naviguideAddDrawnPoint(C.lat, C.lon);
    }, { A, C });
    await expect(page.getByTestId("route-import-error")).toHaveText(text, { timeout: 10_000 });
    await expect(page.getByText(lang === "fr" ? "La ligne droite traverse la terre" : "Straight line crosses land")).toHaveCount(0);
    expect(await page.evaluate(() => window.__naviguideDrawn.points.length)).toBe(2);
  });
}
