// Suivre sur ma route (revue du porteur du 14 oct., B1-B4) :
// Tracer → Terminer → Suivre ouvre Suivre sur la route que je viens de tracer,
// et seulement elle ; les pilules Berry-Mappemonde | <ma route> basculent la
// source dans les deux modes ; une seule route dessinée à la fois.
// Sans API : le dessin (stub /route), les pilules, la route unique, Revoir
// grisé, la date du jour et Play tiennent seuls ; le voyage perso serveur
// (POST /voyage) et Revoir actif côté Berry sont annotés et sautés.
// L'horloge de Suivre × ma route est celle du voyage perso côté client
// (polaire + climatologie) : le serveur répond 202 « en préparation » aux
// brouillons sans forecast (contrat RC15) et n'invente jamais d'horloge.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm5");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

// Signature de la pilule active de la carte route (classe pillOn de BerryCard).
const PILL_ON = /bg-blue-600\/30/;

// La Rochelle → Caraïbes (Antilles).
const START = { lat: 46.1, lon: -1.5 };
const END = { lat: 15.3, lon: -61.0 };

/** Corde déterministe pour le tracé : le spec ne teste pas searoute. */
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

/**
 * Les polylignes du pane `route` (route principale + parcouru), longitudes
 * normalisées dans [-180, 180) pour ignorer les copies de monde (±360).
 */
function routeLines(page) {
  return page.evaluate(() => {
    const map = window.__naviguideScene?.map;
    if (!map) return null;
    const norm = (lon) => ((lon % 360) + 540) % 360 - 180;
    const lines = [];
    map.eachLayer((layer) => {
      if (typeof layer.getLatLngs !== "function" || layer.options?.pane !== "route") return;
      const flat = layer.getLatLngs().flat(Infinity);
      if (!flat.length) return;
      let lonMin = Infinity;
      let lonMax = -Infinity;
      let latMin = Infinity;
      let latMax = -Infinity;
      for (const p of flat) {
        const lon = norm(p.lng);
        if (lon < lonMin) lonMin = lon;
        if (lon > lonMax) lonMax = lon;
        if (p.lat < latMin) latMin = p.lat;
        if (p.lat > latMax) latMax = p.lat;
      }
      const first = flat[0];
      const last = flat[flat.length - 1];
      lines.push({
        n: flat.length,
        lonMin,
        lonMax,
        latMin,
        latMax,
        ends: [[first.lat, norm(first.lng)], [last.lat, norm(last.lng)]],
      });
    });
    return lines;
  });
}

/** Le corridor Atlantique de la route tracée (La Rochelle → Antilles). */
const inCorridor = (l) => l.latMin >= 5 && l.latMax <= 55 && l.lonMin >= -70 && l.lonMax <= 10;
/** La route Berry fait le tour du monde : une ligne hors corridor la trahit. */
const beyondCorridor = (l) => l.lonMax > 60 || l.lonMin < -90;
const nearEnd = (end, p) => Math.abs(end[0] - p.lat) < 0.3 && Math.abs(end[1] - p.lon) < 0.3;
/** La corde tracée (2 sommets, extrémités La Rochelle / Antilles). */
const isDrawnLine = (l) => l.n <= 4 && (
  (nearEnd(l.ends[0], START) && nearEnd(l.ends[1], END))
  || (nearEnd(l.ends[0], END) && nearEnd(l.ends[1], START))
);

test("Tracer → Terminer → Suivre : ma route, seule ; pilules Berry | ma route", async ({ page }) => {
  test.setTimeout(150_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  const officialCalls = [];
  const voyageCreates = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/voyage/official")) officialCalls.push(`${req.method()} ${url}`);
    if (req.method() === "POST" && /\/voyage(\?|$)/.test(url)) voyageCreates.push(url);
  });

  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — voyage perso serveur (POST /voyage) et Revoir actif côté Berry non exigés",
    });
  }

  // Tracer → Tracer votre propre route → La Rochelle → Caraïbes → Terminer.
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("route-switch-draw").click();
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), START);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await page.evaluate(({ lat, lon }) => window.__naviguideAddDrawnPoint(lat, lon), END);
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("here-product")).toBeVisible();
  await expect(page.getByTestId("expedition-story")).toHaveCount(0);

  // Suivre l'expédition → Suivre sur MA route (B1) : l'app ne remet pas Berry.
  const officialBefore = officialCalls.length;
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  // Les pilules de l'encadré gauche : <ma route> active, Berry éteinte.
  await showLeftPanel(page);
  const customPill = page.getByTestId("route-switch-custom");
  await expect(customPill).toBeVisible({ timeout: 10_000 });
  expect((await customPill.getAttribute("class")) || "", "pilule <ma route> active en Suivre").toMatch(PILL_ON);
  expect((await page.getByTestId("route-switch-berry").getAttribute("class")) || "").not.toMatch(PILL_ON);

  // Une seule route à l'écran (B2/B3) : la corde tracée, rien de la Berry.
  await expect.poll(async () => {
    const lines = await routeLines(page);
    return lines?.some(isDrawnLine) || false;
  }, { timeout: 15_000 }).toBe(true);
  const customLines = await routeLines(page);
  expect(customLines.length, "au moins la route tracée").toBeGreaterThan(0);
  expect(customLines.filter(beyondCorridor), "aucune polyline de la route Berry en Suivre × ma route").toEqual([]);
  expect(customLines.every(inCorridor), "toutes les polylines route restent sur ma route").toBe(true);

  // Le bateau est posé sur ma route.
  await expect.poll(async () => page.evaluate(() => {
    const scene = window.__naviguideScene;
    const pos = scene?.mainBoatMarker?.()?.getLatLng?.();
    if (!pos) return null;
    const lon = ((pos.lng % 360) + 540) % 360 - 180;
    return { lat: pos.lat, lon };
  }), { timeout: 15_000 }).toEqual(expect.objectContaining({ lat: expect.any(Number) }));
  const boat = await page.evaluate(() => {
    const pos = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
    const lon = ((pos.lng % 360) + 540) % 360 - 180;
    return { lat: pos.lat, lon };
  });
  expect(boat.lat, "bateau dans le corridor de ma route").toBeGreaterThan(5);
  expect(boat.lat).toBeLessThan(55);
  expect(boat.lon).toBeGreaterThan(-70);
  expect(boat.lon).toBeLessThan(10);

  // Revoir : grisé avec le libellé honnête — jamais retiré.
  const replayStart = page.getByTestId("replay-start");
  await expect(replayStart).toBeVisible();
  await expect(replayStart).toBeDisabled();
  await expect(replayStart).toHaveAttribute(
    "title",
    /en préparation|preparing/,
  );

  // Date de départ = aujourd'hui (08:00 UTC par défaut), éditable en Suivre × ma route.
  await showRightPanel(page);
  const dateInput = page.getByTestId("departure-field").locator('input[name="departure-date"]');
  await expect(dateInput).toBeVisible({ timeout: 10_000 });
  const now = new Date();
  const today = `${String(now.getUTCDate()).padStart(2, "0")}/${String(now.getUTCMonth() + 1).padStart(2, "0")}/${now.getUTCFullYear()}`;
  await expect(dateInput).toHaveValue(today);
  await shot(page, "02-pilules");

  // Pas d'horloge officielle pour ma route : aucun appel /voyage/official de
  // plus ; le voyage perso est bien créé côté serveur (POST /voyage). Son
  // horloge affichée est celle du client (polaire + climatologie) : le
  // serveur répond « en préparation » aux brouillons sans forecast.
  if (apiUp) {
    await expect.poll(() => voyageCreates.length, {
      timeout: 30_000,
    }).toBeGreaterThan(0);
    await page.waitForTimeout(2_000);
    expect(officialCalls.slice(officialBefore), "aucun appel /voyage/official en Suivre × ma route").toEqual([]);
  }

  // Play fait avancer le bateau sur ma route (lecture à la polaire / climato).
  const playButton = page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/);
  await expect(playButton).toBeVisible();
  await expect(page.getByTestId("film-speed")).toBeVisible();
  const nm0 = await page.evaluate(() => window.__naviguideScene?.currentPlayback?.nm ?? 0);
  await playButton.click();
  await expect.poll(async () => page.evaluate(() => window.__naviguideScene?.currentPlayback?.nm ?? 0), {
    timeout: 15_000,
  }).toBeGreaterThan(nm0 + 1);
  await page.getByTestId("film-bar").getByTitle(/^(Pause)$/).click();
  await shot(page, "01-suivre-ma-route");

  // Pilule Berry-Mappemonde → la route Berry seule (passé ET à venir), horloge officielle.
  await page.getByTestId("route-switch-berry").click();
  await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => {
    const lines = await routeLines(page);
    return lines?.some(beyondCorridor) || false;
  }, { timeout: 20_000 }).toBe(true);
  const berryLines = await routeLines(page);
  expect(berryLines.filter(isDrawnLine), "la corde tracée disparaît quand Berry est la source").toEqual([]);
  // Revoir redevient le bouton officiel : le libellé « ma route » disparaît.
  await expect(page.getByTestId("replay-start")).not.toHaveAttribute(
    "title",
    /Berry-Mappemonde seulement|Berry-Mappemonde route only/,
  );
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).toContainText("LIVE", { timeout: 15_000 });
    // Bateau à sa position du jour sur la route Berry : l'horloge officielle
    // le pose loin du corridor Atlantique de ma route (B1 ne revient pas),
    // et la barre affiche l'échantillon live (plus le jour 0 du départ).
    await expect.poll(async () => page.evaluate(() => {
      const pos = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
      if (!pos) return null;
      const lon = ((pos.lng % 360) + 540) % 360 - 180;
      return pos.lat < 5 || pos.lat > 55 || lon < -90 || lon > 60;
    }), { timeout: 30_000 }).toBe(true);
    await expect(page.getByTestId("film-clock-line")).not.toContainText(/ j0 /, { timeout: 15_000 });
    // L'activation de Revoir dépend du film officiel, parfois encore en
    // préparation sur le stock figé : comme rg15, on annote sans échouer.
    let replayEnabled = false;
    for (let i = 0; i < 20 && !replayEnabled; i += 1) {
      replayEnabled = await page.getByTestId("replay-start").isEnabled();
      if (!replayEnabled) await page.waitForTimeout(1_000);
    }
    if (!replayEnabled) {
      test.info().annotations.push({
        type: "Revoir grisé",
        description: "film officiel encore en préparation sur le stock figé — activation non exigée",
      });
    }
  }
  await shot(page, "03-berry");

  // Pilule <ma route> → retour sur la mienne, seule.
  await page.getByTestId("route-switch-custom").click();
  await expect.poll(async () => (await page.getByTestId("route-switch-custom").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect.poll(async () => {
    const lines = await routeLines(page);
    return (lines?.some(isDrawnLine) && !lines.some(beyondCorridor)) || false;
  }, { timeout: 15_000 }).toBe(true);

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
