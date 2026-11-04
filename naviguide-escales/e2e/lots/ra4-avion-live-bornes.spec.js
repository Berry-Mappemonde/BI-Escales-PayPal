// Jambes avion noires pointillées, live stable, longitude bornée.
// Sans API : trait avion (geojson local) et maxBounds se vérifient seuls.
// Position live / rechargement : seulement si GET /voyage/official répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, lngDelta, wrapLng } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-ra4/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

function airLines() {
  const scene = window.__naviguideScene;
  const map = scene?.map;
  if (!map) return [];
  const out = [];
  map.eachLayer((layer) => {
    const opt = layer.options || {};
    if (!layer.getLatLngs || opt.dashArray !== "7 7") return;
    const color = String(opt.color || "").toLowerCase();
    if (color !== "#111111" && color !== "black" && color !== "#111") return;
    out.push({
      color: opt.color,
      dash: opt.dashArray,
      interactive: opt.interactive !== false,
    });
  });
  return out;
}

test("Avion noir pointillé, live stable, longitude bornée", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — position live / rechargement sautés",
    });
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });

  await page.keyboard.press("Escape");

  const bounds = await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    const b = map.options.maxBounds;
    return {
      viscosity: map.options.maxBoundsViscosity,
      south: b.getSouth ? b.getSouth() : b[0][0],
      north: b.getNorth ? b.getNorth() : b[1][0],
      west: b.getWest ? b.getWest() : b[0][1],
      east: b.getEast ? b.getEast() : b[1][1],
    };
  });
  expect(bounds.viscosity).toBe(1);
  expect(bounds.south).toBe(-85);
  expect(bounds.north).toBe(85);
  expect(bounds.west).toBe(-540);
  expect(bounds.east).toBe(540);

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.fire("dragstart");
    scene.map.setView([26, -55], 4, { animate: false });
  });
  await page.waitForTimeout(900);
  await page.waitForFunction(() => document.querySelectorAll(".leaflet-tile-loaded").length > 2, null, { timeout: 12_000 }).catch(() => {});

  const lines = await page.evaluate(airLines);
  expect(lines.length, "trait avion noir pointillé").toBeGreaterThan(0);
  expect(lines.every((l) => l.interactive === false), "jambe avion non cliquable").toBeTruthy();
  expect(lines.every((l) => l.dash === "7 7")).toBeTruthy();

  await shot(page, "01-avion");

  const far = await page.evaluate(() => {
    const map = window.__naviguideScene.map;
    map.setView([0, 700], 3, { animate: false });
    const c = map.getCenter();
    const b = map.getBounds();
    return { lng: c.lng, west: b.getWest(), east: b.getEast() };
  });
  expect(far.lng, `centre ${far.lng}`).toBeLessThanOrEqual(540);
  expect(far.east, `bord est ${far.east}`).toBeLessThanOrEqual(540.2);

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.map.setView([10, 0], 2, { animate: false });
  });
  await page.waitForTimeout(700);
  await shot(page, "02-bornes");

  if (!apiUp) return;

  await page.waitForFunction(() => {
    const m = window.__naviguideScene?.mainBoatMarker?.();
    const ll = m?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  }, null, { timeout: 25_000 }).catch(() => {});

  const first = await page.evaluate(() => {
    const ll = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
    return ll && Number.isFinite(ll.lat) ? { lat: ll.lat, lng: ll.lng } : null;
  });
  if (!first) {
    test.info().annotations.push({
      type: "sans API",
      description: "marqueur bateau absent — stabilité live non vérifiée",
    });
    return;
  }

  await page.reload({ waitUntil: "domcontentloaded" });
  await dismissNotForNav(page);
  await page.getByTestId("view-suivre").click();
  await page.waitForFunction(() => {
    const ll = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
    return Boolean(ll && Number.isFinite(ll.lat));
  }, null, { timeout: 25_000 });
  const second = await page.evaluate(() => {
    const ll = window.__naviguideScene?.mainBoatMarker?.()?.getLatLng?.();
    return { lat: ll.lat, lng: ll.lng };
  });
  const dLat = Math.abs(second.lat - first.lat);
  // Écart de longitude modulo 360 : avant le rechargement la caméra a été promenée à lng 700 puis 0,
  // le marqueur principal peut rester sur la copie +360 ; après rechargement il est sur la copie 0.
  // Même point sur Terre → écart ~0, pas 360 (faux rouge « 3/6 » vu sur #459, #471, #472).
  const dLng = lngDelta(first.lng, second.lng);
  expect(dLat, `saut lat ${first.lat} → ${second.lat}`).toBeLessThan(0.35);
  expect(dLng, `saut lng ${wrapLng(first.lng).toFixed(4)} → ${wrapLng(second.lng).toFixed(4)} (brut ${first.lng} → ${second.lng})`).toBeLessThan(0.35);
});
