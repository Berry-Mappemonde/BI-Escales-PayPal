// Un 422 terre ou traversée s'écrit dans le cadre du tracé.
// Terminer reste grisé. Une paire en mer (réponse routée) l'active.
// GET /voyage/official est sondé : la paire réelle Australie → Californie
// n'est exigée que s'il répond. Le 422 et la paire simulée ne dépendent pas de l'API.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/rx2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const BISCAY = { lat: 46.2, lon: -2.4 };
const PARIS = { lat: 48.8566, lon: 2.3522 };
const LION = { lat: 43.0, lon: 4.2 };
const AUSTRALIA = { lat: -18.2, lon: 153.8 };
const CALIFORNIA = { lat: 34.5, lon: -123.5 };

function ends(url) {
  const q = new URL(url).searchParams;
  return {
    slat: Number(q.get("start_lat")),
    slon: Number(q.get("start_lon")),
    elat: Number(q.get("end_lat")),
    elon: Number(q.get("end_lon")),
  };
}

function inland(lat, lon) {
  return lat > 47 && lon > 0 && lon < 8;
}

function line(slon, slat, elon, elat, km) {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
    properties: { length: km, units: "km" },
  };
}

async function stubRoute(page, { cross = false } = {}) {
  await page.route("**/route?*", async (route) => {
    const { slat, slon, elat, elon } = ends(route.request().url());
    const same = Math.abs(slat - elat) < 1e-4 && Math.abs(slon - elon) < 1e-4;
    if (inland(slat, slon) || inland(elat, elon)) {
      const end = inland(slat, slon) ? "on_land_start" : "on_land_end";
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "on_land", end }),
      });
      return;
    }
    if (cross && !same) {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "crosses_land" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(line(slon, slat, elon, elat, same ? 0 : 12000)),
    });
  });
}

async function openTracer(page) {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
}

function finishButton(page) {
  return page.locator(".naviguide-sidebar-panel.left-0").getByRole("button", { name: /terminer|finish/i });
}

async function frameDrawnLeg(page) {
  const apply = () => page.evaluate(() => {
    const scene = window.__naviguideScene;
    const map = scene?.map;
    const coords = window.__naviguideDrawn?.segments?.[0]?.coords || [];
    if (!map || coords.length < 2) return { ok: false, n: coords.length, hasMap: Boolean(map) };
    const lats = coords.map((c) => Number(c[1]));
    const lons = coords.map((c) => Number(c[0]));
    const south = Math.min(...lats);
    const north = Math.max(...lats);
    const west = Math.min(...lons);
    const east = Math.max(...lons);
    if (scene) {
      scene._worldLockUntil = 0;
      scene.userNavigated = true;
    }
    const fit = () => {
      map.invalidateSize({ animate: false });
      map.fitBounds([[south, west], [north, east]], {
        animate: false,
        padding: [24, 24],
        maxZoom: 4,
      });
    };
    if (typeof scene?.programmaticMove === "function") scene.programmaticMove(fit);
    else fit();
    const center = map.getCenter();
    return {
      ok: true,
      n: coords.length,
      west,
      east,
      south,
      north,
      lat: center.lat,
      lng: center.lng,
      zoom: map.getZoom(),
    };
  });
  await apply();
  await page.waitForTimeout(300);
  return apply();
}

function parseNm(text) {
  const matches = [...String(text || "").matchAll(/(\d[\d\s\u00a0\u202f.,]*)\s*nm/gi)];
  if (!matches.length) return null;
  let raw = matches[matches.length - 1][1].replace(/[\s\u00a0\u202f]/g, "");
  if (/^\d{1,3}([.,]\d{3})+$/.test(raw)) raw = raw.replace(/[.,]/g, "");
  else raw = raw.replace(",", ".");
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && typeof body === "object");
}

test.describe.configure({ mode: "serial" });

let page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page?.close();
});

test.beforeEach(async () => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("un 422 terre s'écrit dans le cadre et Terminer reste grisé", async () => {
  test.setTimeout(90_000);
  await stubRoute(page);
  await openTracer(page);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), BISCAY);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), PARIS);
  const box = page.getByTestId("drawing-box");
  await expect(box).toContainText("Point sur terre : non ajouté", { timeout: 8_000 });
  await expect(box).toContainText("0 nm");
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(1);
  await expect(finishButton(page)).toBeDisabled();
  await shot(page, "01-terre");
});

test("un 422 traversée de terre s'écrit dans le cadre et Terminer reste grisé", async () => {
  test.setTimeout(90_000);
  await stubRoute(page, { cross: true });
  await openTracer(page);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), BISCAY);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), LION);
  const box = page.getByTestId("drawing-box");
  await expect(box).toContainText("La ligne droite traverse la terre", { timeout: 8_000 });
  await expect(box).toContainText("0 nm");
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0)).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.segments?.length || 0)).toBe(0);
  await expect(finishButton(page)).toBeDisabled();
  await shot(page, "02-traversee");
});

test("deux points en mer activent Terminer", async () => {
  test.setTimeout(90_000);
  await stubRoute(page);
  await openTracer(page);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), AUSTRALIA);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), CALIFORNIA);
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 1, null, { timeout: 15_000 });
  const box = page.getByTestId("drawing-box");
  await expect(box).not.toContainText("Point sur terre");
  await expect(box).not.toContainText("traverse la terre");
  const summary = await page.getByTestId("drawing-summary").innerText();
  const nm = parseNm(summary);
  expect(nm, summary).toBeGreaterThan(0);
  await expect(finishButton(page)).toBeEnabled();
  const frame = await frameDrawnLeg(page);
  expect(frame.lng, JSON.stringify(frame)).toBeGreaterThan(140);
  await shot(page, "03-mer");
});

test("paire réelle en mer : route et Terminer, si l'API répond", async () => {
  test.setTimeout(180_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — paire réelle Australie → Californie non exigée",
    });
    return;
  }
  await openTracer(page);
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), AUSTRALIA);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) === 1, null, { timeout: 15_000 });
  await page.evaluate((p) => window.__naviguideAddDrawnPoint(p.lat, p.lon), CALIFORNIA);
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) >= 1, null, { timeout: 90_000 });
  const box = page.getByTestId("drawing-box");
  await expect(box).not.toContainText("Point sur terre");
  await expect(box).not.toContainText("traverse la terre");
  const summary = await page.getByTestId("drawing-summary").innerText();
  expect(parseNm(summary), summary).toBeGreaterThan(1000);
  await expect(finishButton(page)).toBeEnabled();
  const frame = await frameDrawnLeg(page);
  expect(frame.lng, JSON.stringify(frame)).toBeGreaterThan(140);
  await shot(page, "04-mer-reelle");
});
