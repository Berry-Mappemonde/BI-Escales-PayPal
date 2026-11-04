// Pendant le dessin d'une route perso, POST /ici/layers/warm et
// GET /ici?thin=1 partent sur le brouillon (pas d'attente du Terminer).
// Sans API : le dessin (stub /route) et les requêtes client tiennent seuls.
// GET /voyage/official est sondé ; s'il manque, annotation — les assertions
// réseau du brouillon ne dépendent pas de lui et restent exigées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-ly2");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const START = { lat: 46.157, lon: -1.151 };
const MID = { lat: 45.4, lon: -1.2 };
const END = { lat: 44.7, lon: -1.25 };

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

test("Le brouillon chauffe avant Terminer ; Annuler coupe", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const warmPosts = [];
  const thinGets = [];
  const isDraftThin = (url) => {
    try {
      const u = new URL(url);
      const lat = Number(u.searchParams.get("lat"));
      const lon = Number(u.searchParams.get("lon"));
      return lat > 44 && lat < 47 && lon > -2 && lon < 0;
    } catch {
      return false;
    }
  };
  page.on("request", (req) => {
    const url = req.url();
    if (req.method() === "POST" && url.includes("/ici/layers/warm")) warmPosts.push(url);
    if (req.method() === "GET" && /\/ici\?/.test(url) && url.includes("thin=1") && isDraftThin(url)) {
      thinGets.push(url);
    }
  });

  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions réseau du brouillon conservées (POST warm + GET thin)",
    });
  }

  await enterTracer(page);
  await expect(page.getByTestId("route-import")).toBeVisible();
  await expect(page.getByRole("button", { name: /annuler|cancel/i }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /terminer|finish/i })).toBeVisible();

  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), START);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  const warmBefore = warmPosts.length;
  const thinBefore = thinGets.length;
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), MID);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), END);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 3, { timeout: 15_000 });

  await expect.poll(() => warmPosts.length - warmBefore, { timeout: 8_000 }).toBeGreaterThanOrEqual(1);
  await expect.poll(() => thinGets.length - thinBefore, { timeout: 8_000 }).toBeGreaterThanOrEqual(1);
  expect(warmPosts.length - warmBefore, "pas un POST par clic (debounce)").toBeLessThanOrEqual(2);

  await expect(page.getByTestId("route-import")).toBeVisible();
  await expect(page.getByRole("button", { name: /terminer|finish/i })).toBeVisible();
  await expect(page.getByText(/préchauff|chauffe des couches|perles en cours/i)).toHaveCount(0);
  await shot(page, "01-trace-deux-clics");

  const warmAfterDraw = warmPosts.length;
  await page.getByRole("button", { name: /annuler|cancel/i }).first().click();
  await expect(page.getByTestId("drawing-box")).toHaveCount(0);
  await page.waitForTimeout(2000);
  expect(warmPosts.length, "Annuler : plus aucun POST /ici/layers/warm").toBe(warmAfterDraw);

  if (apiUp) {
    await page.getByTestId("view-suivre").click();
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 15_000 });
    await shot(page, "02-suivre-inchange");
  }

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
