// Tracer, c'est d'abord tracer (revue du porteur, 14 oct. §1.C) :
// entrée en Tracer = dessin ouvert ; la pilule Berry-Mappemonde affiche la
// route Berry sans Annuler et sans jeter le brouillon ; « Tracer votre propre
// route » le ramène ; Annuler reste le seul abandon. Importer reste.
// Sans API : le dessin (stub /route), Berry ↔ brouillon, Terminer et Annuler
// tiennent seuls. GET /voyage/official sondé ; s'il manque, annotation + saut
// des seules assertions qui en dépendent (Saint-Maur sur la vitrine Berry).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm6");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const PILL_ON = /bg-blue-600\/30/;
const START = { lat: 46.1, lon: -1.5 };
const END = { lat: 15.3, lon: -61.0 };

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

test("Tracer ouvre le dessin ; Berry met le brouillon de côté", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — vitrine Berry (Saint-Maur) non exigée ; dessin, aller-retour et Annuler conservés",
    });
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText(/Choisissez votre point de départ|Choose your starting point/).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("route-import")).toBeVisible();
  await expect(page.getByRole("button", { name: /annuler|cancel/i }).first()).toBeVisible();
  const drawPill = page.getByTestId("route-switch-draw");
  await expect(drawPill).toBeVisible();
  expect((await drawPill.getAttribute("class")) || "", "pilule de tracé active").toMatch(PILL_ON);
  await shot(page, "01-tracer-defaut");

  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), START);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), END);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });

  await page.getByTestId("route-switch-berry").click();
  await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("drawing-box")).toHaveCount(0);
  await expect(page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/)).toBeVisible();
  await expect.poll(async () => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), {
    timeout: 5_000,
  }).toBe(2);
  if (apiUp) {
    await expect(page.getByText(/Saint-Maur/i).first()).toBeVisible({ timeout: 20_000 });
  }

  await page.getByTestId("route-switch-draw").click();
  await expect(page.getByTestId("drawing-box")).toBeVisible({ timeout: 10_000 });
  await expect.poll(async () => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), {
    timeout: 8_000,
  }).toBe(2);
  expect((await page.getByTestId("route-switch-draw").getAttribute("class")) || "").toMatch(PILL_ON);
  await shot(page, "02-brouillon-revenu");

  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  const customPill = page.getByTestId("route-switch-custom");
  await expect(customPill).toBeVisible({ timeout: 10_000 });
  expect((await customPill.getAttribute("class")) || "", "Terminer → ma route").toMatch(PILL_ON);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/)).toBeVisible();

  const continueBtn = page.getByRole("button", { name: /Continuer le tracé|Continue drawing/i });
  await expect(continueBtn).toBeVisible({ timeout: 10_000 });
  await continueBtn.click();
  await expect(page.getByTestId("drawing-box")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /annuler|cancel/i }).first().click();
  await expect(page.getByTestId("drawing-box")).toHaveCount(0);
  await expect.poll(async () => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), {
    timeout: 8_000,
  }).toBe(0);
  await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
