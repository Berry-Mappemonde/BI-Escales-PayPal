// Route copiée jusqu'à la butée droite ; survol du trait parcouru.
// Sans API : copies de route (geojson local) et bornes se vérifient seules.
// Survol hindcast / jambe avion : seulement si GET /voyage/official répond
// et qu'un trait parcouru expose déjà une vitesse d'époque (jamais inventée).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb8/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function inspectMap() {
  const flatten = (raw) => {
    const out = [];
    const walk = (value) => {
      if (!value) return;
      if (Array.isArray(value)) {
        value.forEach(walk);
        return;
      }
      if (typeof value.lat === "number" && typeof value.lng === "number") out.push(value);
    };
    walk(raw);
    return out;
  };
  const map = window.__naviguideScene?.map;
  if (!map) {
    return { east: { count: 0, max: null, west: null, east: null }, hover: null, air: null };
  }
  const bounds = map.getBounds();
  const lons = [];
  let hover = null;
  let air = null;
  map.eachLayer((layer) => {
    if (!layer.getLatLngs) return;
    const opt = layer.options || {};
    const pts = flatten(layer.getLatLngs());
    if (opt.dashArray !== "7 7") {
      for (const point of pts) {
        if (point.lng >= 300 && point.lng <= 540) lons.push(point.lng);
      }
    }
    if (!hover && layer.getTooltip && layer.getTooltip()) {
      const content = String(layer.getTooltip().getContent() || "");
      if (content.includes("traveled-era-speed")) {
        const mid = pts[Math.floor(pts.length / 2)] || pts[0];
        if (mid) {
          const pt = map.latLngToContainerPoint(mid);
          hover = { x: pt.x, y: pt.y, content };
        }
      }
    }
    if (!air && opt.dashArray === "7 7") {
      const color = String(opt.color || "").toLowerCase();
      if (color === "#111111" || color === "black" || color === "#111") {
        const mid = pts[Math.floor(pts.length / 2)] || pts[0];
        if (mid) {
          const pt = map.latLngToContainerPoint(mid);
          air = { x: pt.x, y: pt.y };
        }
      }
    }
  });
  return {
    east: {
      count: lons.length,
      max: lons.length ? Math.max(...lons) : null,
      west: bounds.getWest(),
      east: bounds.getEast(),
    },
    hover,
    air,
  };
}

test("Copie droite du trajet et survol du parcouru", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — survol hindcast non vérifié (jamais inventé)",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await page.keyboard.press("Escape");
  const closeCard = page.getByRole("button", { name: /fermer|close/i }).first();
  if (await closeCard.isVisible({ timeout: 800 }).catch(() => false)) await closeCard.click();

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.fire("dragstart");
    scene.map.setView([12, 420], 2, { animate: false });
  });
  await page.waitForTimeout(700);
  await page.waitForFunction(() => document.querySelectorAll(".leaflet-tile-loaded").length > 2, null, { timeout: 12_000 }).catch(() => {});

  const right = await page.evaluate(inspectMap);
  expect(right.east.count, `points de route dans la fenêtre est (${right.east.west}–${right.east.east})`).toBeGreaterThan(10);
  expect(right.east.max, "le trajet atteint le côté africain à droite").toBeGreaterThan(400);
  await shot(page, "01-copie-droite");

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.map.setView([36, -20], 4, { animate: false });
  });
  await page.waitForTimeout(600);

  const mid = await page.evaluate(inspectMap);
  const box = await page.locator(".leaflet-container").boundingBox();
  expect(box).toBeTruthy();

  if (!mid.hover) {
    test.info().annotations.push({
      type: apiUp ? "poste" : "sans API",
      description: "hindcast en cours — aucun trait parcouru avec vitesse d'époque, info-bulle non forcée",
    });
    await shot(page, "02-survol");
    return;
  }

  await page.mouse.move(box.x + mid.hover.x, box.y + mid.hover.y);
  await expect(page.getByTestId("traveled-era-speed").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByTestId("traveled-era-speed").first()).toHaveText(/\d+[.,]\d+\s*kn/);
  await shot(page, "02-survol");

  if (mid.air) {
    await page.mouse.move(box.x + 8, box.y + 8);
    await page.waitForTimeout(200);
    await page.mouse.move(box.x + mid.air.x, box.y + mid.air.y);
    await page.waitForTimeout(350);
    await expect(page.getByTestId("traveled-era-speed")).toHaveCount(0);
  }
});
