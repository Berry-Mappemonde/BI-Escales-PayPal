// Clic route → pop-up Copernicus ; clic drapeau n'ouvre pas le
// panneau gauche ; plus de carré vert ▤ dans la liste des escales.
// Sans API : le pop-up s'ouvre (fetch météo en repli), les onglets Vent /
// Vagues / Courants et l'absence de ▤ tiennent seuls. GET /voyage/official
// sondé ; s'il manque, on annote et on saute seulement les assertions
// drapeau / fiche Ici, jamais le hit-test route ni l'absence de ▤.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  return page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function leftPanel(page) {
  return page.locator(".naviguide-sidebar-panel.left-0").first();
}

function leftPanelOpen(page) {
  return leftPanel(page).evaluate((el) => !el.className.includes("-translate-x-full"));
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  if (await leftPanelOpen(page)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect.poll(() => leftPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

async function hideLeftPanel(page) {
  if (!(await leftPanelOpen(page))) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect.poll(() => leftPanelOpen(page), { timeout: 10_000 }).toBe(false);
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showRightPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
  await page.waitForTimeout(350);
}

async function fireRouteClick(page, lonShift = 0) {
  return page.evaluate((shift) => {
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
    if (!map) return null;
    let mid = null;
    map.eachLayer((layer) => {
      if (!layer.getLatLngs) return;
      const opt = layer.options || {};
      if (opt.dashArray === "7 7") return;
      const pts = flatten(layer.getLatLngs());
      if (pts.length < 2) return;
      const candidate = pts[Math.floor(pts.length / 2)];
      if (!mid || Math.abs(candidate.lng) < 180) mid = candidate;
    });
    if (!mid) return null;
    const latlng = { lat: mid.lat, lng: mid.lng + shift };
    map.fire("click", { latlng });
    return latlng;
  }, lonShift);
}

async function expectCopernicus(page) {
  const popup = page.getByTestId("satellite-popup");
  await expect(popup).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("satellite-tab-wind")).toBeVisible();
  await expect(page.getByTestId("satellite-tab-waves")).toBeVisible();
  await expect(page.getByTestId("satellite-tab-currents")).toBeVisible();
  await expect(popup.getByRole("button", { name: /Vent|Wind/ })).toBeVisible();
  await expect(popup.getByRole("button", { name: /Vagues|Waves/ })).toBeVisible();
  await expect(popup.getByRole("button", { name: /Courants|Currents/ })).toBeVisible();
}

async function closeCopernicus(page) {
  const close = page.getByTestId("satellite-popup-close");
  if (await close.isVisible().catch(() => false)) await close.click();
  await expect(page.getByTestId("satellite-popup")).toHaveCount(0);
}

async function clickAjaccioFlag(page) {
  const found = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 20_000 }).then(() => true).catch(() => false);
  if (!found) return false;
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) {
        scene.map.setView(marker.getLatLng(), 7, { animate: false });
        marker.fire("click");
        return;
      }
    }
  });
  return true;
}

test("Clic route Copernicus, drapeau sans panneau, plus de ▤", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — drapeau / fiche Ici non exigés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.fire("dragstart");
    scene.map.setView([36, -20], 3, { animate: false });
  });
  await page.waitForTimeout(500);

  const base = await fireRouteClick(page, 0);
  expect(base, "aucun trait mer cliquable sur la copie de base").toBeTruthy();
  await expectCopernicus(page);

  await closeCopernicus(page);
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.map.setView([12, 420], 2, { animate: false });
  });
  await page.waitForTimeout(600);
  await page.waitForFunction(() => document.querySelectorAll(".leaflet-tile-loaded").length > 2, null, { timeout: 12_000 }).catch(() => {});

  const copy = await fireRouteClick(page, 0);
  expect(copy, "aucun trait mer cliquable sur la copie est").toBeTruthy();
  await expectCopernicus(page);

  await closeCopernicus(page);
  const wrapped = await fireRouteClick(page, 360);
  expect(wrapped, "clic simulé à lng+360 sans trait").toBeTruthy();
  await expectCopernicus(page);
  await page.waitForFunction(() => document.querySelectorAll(".leaflet-tile-loaded").length > 2, null, { timeout: 12_000 }).catch(() => {});
  await shot(page, "01-copernicus");

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.map.setView([36, -20], 6, { animate: false });
  });
  await page.waitForTimeout(400);
  await closeCopernicus(page);
  const zoomed = await fireRouteClick(page, 0);
  expect(zoomed, "trait mer invisible au zoom fort").toBeTruthy();
  await expectCopernicus(page);
  await closeCopernicus(page);

  await hideLeftPanel(page);
  await expect.poll(() => leftPanelOpen(page)).toBe(false);

  if (apiUp) {
    const flagged = await clickAjaccioFlag(page);
    if (flagged) {
      await page.waitForTimeout(400);
      expect(await leftPanelOpen(page), "le clic drapeau a ouvert le panneau gauche").toBe(false);
      await expect(page.getByTestId("satellite-popup")).toHaveCount(0);

      await showLeftPanel(page);
      await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 10_000 });
      await clickAjaccioFlag(page);
      const sheet = page.getByTestId("ici-maintenant").getByTestId("escale-sheet");
      await expect(sheet).toBeVisible({ timeout: 10_000 });
      await expect(sheet).toContainText(/Ajaccio/i);
    } else {
      test.info().annotations.push({
        type: "drapeau",
        description: "aucun drapeau Ajaccio — clic drapeau non joué",
      });
    }
  }

  await showRightPanel(page);
  const legend = page.getByTestId("escale-legend");
  await expect(legend).toBeVisible({ timeout: 10_000 });
  await legend.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("escale-sheet-open")).toHaveCount(0);
  await expect(legend).not.toContainText("▤");
  await shot(page, "02-escales");
});
