// Zoom +/− horizontal, compact, en bas à droite à côté des crédits.
// Sans API : le contrôle Leaflet et le zoom tiennent seuls.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rb2/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  return page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
}

async function zoomLayout(page) {
  return page.evaluate(() => {
    const zoom = document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    const topLeft = document.querySelector(".leaflet-top.leaflet-left .leaflet-control-zoom");
    const plus = document.querySelector(".leaflet-control-zoom-in");
    const minus = document.querySelector(".leaflet-control-zoom-out");
    const attr = document.querySelector(".leaflet-control-attribution");
    if (!zoom || !plus || !minus) return { ok: false };
    const zr = zoom.getBoundingClientRect();
    const pr = plus.getBoundingClientRect();
    const mr = minus.getBoundingClientRect();
    const ar = attr?.getBoundingClientRect();
    return {
      ok: true,
      inTopLeft: Boolean(topLeft),
      inBottomRight: Boolean(zoom),
      horizontal: Math.abs(pr.top - mr.top) <= 3 && pr.right <= mr.left + 2,
      plusW: pr.width,
      plusH: pr.height,
      zoomBottom: zr.bottom,
      zoomRight: zr.right,
      attrText: (attr?.textContent || "").replace(/\s+/g, " ").trim(),
      attrVisible: Boolean(ar && ar.width > 40 && ar.height > 8),
      attrLeft: ar?.left ?? 0,
      attrBottom: ar?.bottom ?? 0,
      overlapAttr: Boolean(ar && zr.right > ar.left + 2 && zr.left < ar.right - 2 && zr.bottom > ar.top + 2 && zr.top < ar.bottom - 2),
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
    };
  });
}

async function assertZoomCorner(page, { filmBar = true } = {}) {
  const layout = await zoomLayout(page);
  expect(layout.ok, "contrôle de zoom présent").toBeTruthy();
  expect(layout.inTopLeft, "plus de zoom en haut à gauche").toBeFalsy();
  expect(layout.inBottomRight, "zoom en bas à droite").toBeTruthy();
  expect(layout.horizontal, "+ et − côte à côte").toBeTruthy();
  expect(layout.plusH, `hauteur + ${layout.plusH} ≥ 26 (défaut Leaflet)`).toBeLessThan(26);
  expect(layout.plusW, `largeur + ${layout.plusW} ≥ 26`).toBeLessThan(26);
  expect(layout.attrVisible, "crédits visibles").toBeTruthy();
  expect(layout.attrText).toMatch(/Leaflet/);
  expect(layout.attrText).toMatch(/Esri/);
  expect(layout.attrText).toMatch(/HERE/);
  expect(layout.attrText).toMatch(/Garmin/);
  expect(layout.attrText).toMatch(/OpenStreetMap/);
  expect(layout.overlapAttr, "zoom ne recouvre pas les crédits").toBeFalsy();
  expect(layout.zoomRight, "zoom trop à droite de l'écran").toBeLessThanOrEqual(layout.viewportW);
  expect(layout.zoomBottom, "zoom trop bas").toBeLessThanOrEqual(layout.viewportH);
  if (filmBar) {
    const bar = page.getByTestId("film-bar");
    await expect(bar).toBeVisible();
    const barBox = await bar.boundingBox();
    expect(barBox, "barre de lecture mesurable").toBeTruthy();
    // Barre plus haute (pilules dans le cadre) — zoom et crédits restent
    // dans la bande basse, sans recouvrir le milieu de carte.
    expect(layout.zoomBottom, "zoom dans la bande basse").toBeGreaterThan(layout.viewportH - 160);
    expect(layout.attrBottom, "crédits dans la bande basse").toBeGreaterThan(layout.viewportH - 160);
    expect(layout.zoomBottom, "zoom ne monte pas au milieu").toBeLessThan(barBox.y + 40);
  }
  return layout;
}

test("Zoom horizontal compact bas droite", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — le zoom et les crédits se vérifient sans elle",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });

  await assertZoomCorner(page, { filmBar: true });

  const z0 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
  await page.locator(".leaflet-control-zoom-in").click();
  await page.waitForFunction((prev) => window.__naviguideScene.map.getZoom() > prev, z0, { timeout: 5_000 });
  const z1 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
  expect(z1, `zoom ${z0} → ${z1}`).toBeGreaterThan(z0);
  await page.locator(".leaflet-control-zoom-out").click();
  await page.waitForFunction((prev) => window.__naviguideScene.map.getZoom() < prev, z1, { timeout: 5_000 });

  await shot(page, "01-zoom");

  const leftToggle = page.locator(".naviguide-sidebar-toggle--left");
  const rightToggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await leftToggle.isVisible().catch(() => false)) await leftToggle.click();
  if (await rightToggle.isVisible().catch(() => false)) await rightToggle.click();
  await page.waitForTimeout(350);
  await assertZoomCorner(page, { filmBar: true });

  if (await leftToggle.isVisible().catch(() => false)) await leftToggle.click();
  if (await rightToggle.isVisible().catch(() => false)) await rightToggle.click();
  await page.waitForTimeout(350);

  const hide = page.getByTestId("hide-film-bar");
  if (await hide.isVisible().catch(() => false)) {
    await hide.click();
    await expect(page.getByTestId("show-film-bar")).toBeVisible({ timeout: 5_000 });
    await assertZoomCorner(page, { filmBar: false });
    const zoom = page.locator(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    await expect(zoom).toBeVisible();
    await page.getByTestId("show-film-bar").click();
    await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 5_000 });
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await assertZoomCorner(page, { filmBar: true });
});
