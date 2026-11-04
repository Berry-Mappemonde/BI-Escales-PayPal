// Ménage des identifiants « simulation » dans le client
// Aucun changement visible : le parcours
// Suivre → Tracer → Tracer votre propre route → Terminer → Suivre est celui
// de la veille. VIEW_TRACER / isTracer / mode-tracer ; le protocole serveur
// reste "simulation". Sans API : le dessin (stub /route) et les pilules
// tiennent seuls ; GET /voyage/official est sondé — s'il manque, annotation
// et saut des seules assertions qui en dépendent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm3");
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

test("Suivre → Tracer → Tracer votre propre route → Terminer → Suivre, identique à la veille", async ({ page }) => {
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
      description: "GET /voyage/official absent — horloge officielle non exigée ; pilules, dessin et Terminer conservés",
    });
  }

  const switcher = page.getByTestId("film-view-switch");
  await expect(switcher.getByRole("radio")).toHaveCount(2);
  await expect(page.getByTestId("view-suivre")).toBeVisible();
  await expect(page.getByTestId("view-tracer")).toBeVisible();
  expect(await page.getByTestId("view-simulation").count()).toBe(0);
  expect(await page.locator("[data-mode='mode-sim']").count()).toBe(0);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("data-mode", "mode-tracer");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).toContainText("LIVE", { timeout: 15_000 });
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("data-mode", "mode-tracer");
  await expect(page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/)).toBeVisible();
  await expect(page.getByText(/Choisissez votre point de départ|Choose your starting point/).first()).toBeVisible({ timeout: 10_000 });
  const drawPill = page.getByTestId("route-switch-draw");
  await expect(drawPill).toHaveText(/Tracer votre propre route|Draw your own route/);
  expect((await drawPill.getAttribute("class")) || "", "pilule Tracer votre propre route active").toMatch(PILL_ON);

  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), START);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), END);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });

  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  const customPill = page.getByTestId("route-switch-custom");
  await expect(customPill).toBeVisible({ timeout: 10_000 });
  expect((await customPill.getAttribute("class")) || "", "Terminer → ma route").toMatch(PILL_ON);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await showLeftPanel(page);
  await expect(page.getByTestId("route-switch-custom")).toBeVisible();

  await shot(page, "01-parcours");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
