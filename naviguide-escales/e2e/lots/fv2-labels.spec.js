// Popup de climatologie : phrase lisible, jamais « kind: ».
// Tuiles et point d'atlas factices — aucun appel Nebius ni Tavily.
// GET /voyage/official : s'il manque, les assertions de route sont sautées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/fv2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const POINT = {
  kind: "climatology",
  month: 5,
  wind_atlas: { most_likely: { speed_knots: 14, dir_deg: 60 } },
  coordinates: { cell_selection: "fixture" },
};

const TILE = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    geometry: { type: "Point", coordinates: [-40, 20] },
    properties: {
      speed_knots: 14,
      dir_from_deg: 60,
      wind_speed_knots: 14,
      wind_direction_from_deg: 60,
      month: 5,
    },
  }],
};

const ROAD = /Transfert routier Saint-Maur \(Indre\) → La Rochelle : \d[\d\s\u202f]* km, ≈ \d+ h|Road transfer Saint-Maur \(Indre\) → La Rochelle: \d[\d,\s]* km, ≈ \d+ h/;
const PORT = /\d[\d\s\u202f\u00a0,.]* nm (jusqu’au port de destination|to destination port)/;
const FOREIGN = /Açores \(Corse\)|Azores \(Corse\)|Azores \(Corsica\)/;

async function officialUp(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && typeof body === "object");
}

test("popup climatologie sans « kind: »", async ({ page }) => {
  test.setTimeout(90_000);
  await page.route("**/climatology/wind/tiles/**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(TILE) });
  });
  await page.route("**/climatology/point**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(POINT) });
  });
  await page.route("**/climatology/wind.geojson**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(TILE) });
  });

  await page.goto("/?climo=wind&map=20,-40,3&month=5");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  const banner = page.getByTestId("climatology-banner");
  await expect(banner).toBeVisible({ timeout: 15_000 });
  await expect(banner).not.toContainText(/kind/i);

  await expect.poll(async () => page.evaluate(() => {
    const map = window.__naviguideScene?.map;
    if (!map) return "no-map";
    const latlng = map.getCenter();
    map.fire("click", { latlng });
    return document.querySelector("[data-testid='climatology-map-popup']") ? "open" : "waiting";
  }), { timeout: 15_000 }).toBe("open");

  const popup = page.getByTestId("climatology-map-popup");
  await expect(popup).toBeVisible();
  const text = await popup.innerText();
  expect(text).not.toMatch(/kind:/);
  expect(text).toMatch(/Climatologie — moyenne mensuelle \(mai\), pas une prévision|Climatology — monthly average \(May\), not a forecast/);
  const size = await page.getByTestId("climatology-caption").first().evaluate((el) => (
    Number.parseFloat(getComputedStyle(el).fontSize)
  ));
  expect(size).toBeGreaterThanOrEqual(12);
  await shot(page, "01-climatologie");

  const apiUp = await officialUp(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions de route et de port sautées",
    });
    return;
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const rows = page.getByTestId("escale-legend-row");
  const n = await rows.count();
  for (let i = 0; i < n; i += 1) {
    const label = await rows.nth(i).innerText();
    expect(label, "suffixe d'une autre escale").not.toMatch(FOREIGN);
  }

  const land = page.getByTestId("film-land-leg");
  const landVisible = await land.isVisible({ timeout: 8000 }).catch(() => false);
  if (landVisible) {
    await expect(land).toContainText(ROAD);
    await expect(land).not.toContainText(/\bnm\b/);
    const clock = await page.getByTestId("film-clock-line").innerText();
    expect(clock).not.toMatch(/^\s*[\d\s\u202f\u00a0.,]+\s*nm\b/);
    await shot(page, "02-transfert-routier");
  } else {
    test.info().annotations.push({
      type: "hors Saint-Maur",
      description: "horloge officielle hors jambe terrestre — libellé km non affiché",
    });
  }

  await showLeftPanel(page);
  const port = page.getByTestId("nm-to-destination-port");
  await expect(port).toBeVisible({ timeout: 15_000 });
  const portText = (await port.innerText()).replace(/[\u202f\u00a0]/g, " ");
  expect(portText).not.toMatch(/\bPORT\b/);
  if (portText !== "—") expect(portText).toMatch(PORT);
  await shot(page, "03-distance-port");
});
