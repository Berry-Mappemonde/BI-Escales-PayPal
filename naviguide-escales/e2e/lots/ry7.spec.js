// Route publiée : le fichier statique, pas l'API voyage.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation
// et retour — les assertions de barre et de route.geojson ne sont pas sautées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ry7");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const PANAMA = { lonMin: -81, latMin: 8.5, lonMax: -79, latMax: 9.7 };
const SUEZ = { lonMin: 32, latMin: 29.7, lonMax: 32.7, latMax: 31.5 };

function inBox(lon, lat, box) {
  return lon >= box.lonMin && lon <= box.lonMax && lat >= box.latMin && lat <= box.latMax;
}

test("Suivre montre le trait publié, Tracer n'ajoute pas de bouton", async ({ page }) => {
  test.setTimeout(60_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  let apiBody = null;
  if (official && official.ok()) {
    const ct = (official.headers()["content-type"] || "").toLowerCase();
    if (ct.includes("json")) apiBody = await official.json().catch(() => null);
  }
  const apiUp = Boolean(apiBody && typeof apiBody === "object" && !Array.isArray(apiBody));

  const routeRes = await page.request.get("/route.geojson");
  expect(routeRes.ok()).toBeTruthy();
  const fc = await routeRes.json();
  const features = fc.features || [];
  expect(features.length).toBe(72);
  const lines = features.filter((f) => f.geometry?.type === "LineString");
  const maritime = lines.filter((f) => f.properties?.type === "maritime");
  const overland = lines.filter((f) => f.properties?.type === "overland");
  expect(maritime).toHaveLength(35);
  expect(overland).toHaveLength(1);
  expect(String(overland[0].properties?.from || "")).toContain("Saint-Maur");
  expect(overland[0].properties?.to).toBe("La Rochelle");
  const cayenne = maritime.find((f) => (
    String(f.properties?.from || "").includes("Cayenne")
    && String(f.properties?.to || "").includes("Papeete")
  ));
  expect(cayenne, "Cayenne → Papeete").toBeTruthy();
  expect(cayenne.geometry.coordinates.some(([lon, lat]) => inBox(lon, lat, PANAMA))).toBe(true);
  const suezHits = features.flatMap((f) => {
    const g = f.geometry || {};
    const coords = g.type === "Point" ? [g.coordinates] : (g.coordinates || []);
    return coords.filter((c) => Array.isArray(c) && c.length >= 2 && inBox(c[0], c[1], SUEZ));
  });
  expect(suezHits).toEqual([]);
  const halifax = (from, to) => maritime.filter((f) => (
    String(f.properties?.from || "").includes(from)
    && String(f.properties?.to || "").includes(to)
  ));
  expect(halifax("Halifax", "Saint-Pierre")).toHaveLength(1);
  expect(halifax("Saint-Pierre", "Halifax")).toHaveLength(1);
  const cayenneHalifax = features.filter((f) => {
    const from = String(f.properties?.from || "");
    const to = String(f.properties?.to || "");
    return (from.includes("Cayenne") && to.includes("Halifax"))
      || (from.includes("Halifax") && to.includes("Cayenne"));
  });
  expect(cayenneHalifax).toEqual([]);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-suivre")).toContainText("Suivre");
  await expect(page.getByTestId("replay-start")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toContainText("Revoir");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await page.waitForFunction(() => {
    const map = window.__naviguideScene?.map;
    if (!map?.eachLayer) return false;
    let count = 0;
    map.eachLayer((layer) => {
      if (typeof layer.getLatLngs !== "function") return;
      const latLngs = layer.getLatLngs();
      const flat = Array.isArray(latLngs?.[0]) ? latLngs.flat(3) : latLngs;
      count += Array.isArray(flat) ? flat.length : 0;
    });
    return count > 500;
  }, null, { timeout: 30_000 });
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-tracer")).toContainText("Tracer");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
  await shot(page, "02-tracer");

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — lecture du voyage sautée ; barre, Suivre, Tracer et route.geojson exigés",
    });
    return;
  }

  expect(apiBody && typeof apiBody === "object", "GET /voyage/official répond en JSON").toBeTruthy();
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
});
