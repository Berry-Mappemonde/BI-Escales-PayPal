// Habillage carte : crédits/zoom translucides, chevrons alignés,
// rond de tracé centré sous le clic. Sans API : bande, toggles et pin
// tiennent seuls. GET /voyage/official sondé ; s'il manque, annotation
// seulement (aucune assertion n'en dépend).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd2/${name}.webp`,
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

function leftPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.left-0").first().evaluate((el) => (
    !el.className.includes("-translate-x-full")
  ));
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function setLeftPanel(page, open) {
  await leaveCinema(page);
  if (await leftPanelOpen(page) === open) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect.poll(() => leftPanelOpen(page), { timeout: 10_000 }).toBe(open);
}

async function setRightPanel(page, open) {
  await leaveCinema(page);
  if (await rightPanelOpen(page) === open) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(open);
}

async function toggleTops(page) {
  const left = page.locator(".naviguide-sidebar-toggle--left");
  const right = page.locator(".naviguide-sidebar-toggle--right");
  await expect(left).toBeVisible();
  await expect(right).toBeVisible();
  const lb = await left.boundingBox();
  const rb = await right.boundingBox();
  return { left: lb.y, right: rb.y, delta: Math.abs(lb.y - rb.y) };
}

function parseRgba(value) {
  const m = String(value || "").match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
  if (!m) return null;
  return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]), a: m[4] == null ? 1 : Number(m[4]) };
}

async function creditGeometry(page) {
  return page.evaluate(() => {
    const attr = document.querySelector(".leaflet-control-attribution");
    const zoom = document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    const chrome = document.querySelector("[data-testid='film-bar']")
      || document.querySelector("[data-testid='show-film-bar']");
    if (!attr || !zoom || !chrome) return { ok: false };
    const a = attr.getBoundingClientRect();
    const z = zoom.getBoundingClientRect();
    const b = chrome.getBoundingClientRect();
    return {
      ok: true,
      attrH: a.height,
      zoomH: z.height,
      attrBottom: a.bottom,
      barTop: b.top,
      gap: b.top - a.bottom,
    };
  });
}

async function assertAttributionOnBar(page, label) {
  await expect.poll(async () => {
    const g = await creditGeometry(page);
    if (!g.ok) return `absent (${label})`;
    const heightOk = Math.abs(g.attrH - g.zoomH) <= 0.5;
    const gapOk = g.attrBottom <= g.barTop - 2 && g.attrBottom >= g.barTop - 12;
    return heightOk && gapOk ? "ok" : `h=${g.attrH}/${g.zoomH} gap=${g.gap.toFixed(2)} (${label})`;
  }, { timeout: 8_000 }).toBe("ok");
  const g = await creditGeometry(page);
  expect(Math.abs(g.attrH - g.zoomH), `hauteur attribution ${g.attrH} vs zoom ${g.zoomH} (${label})`).toBeLessThanOrEqual(0.5);
  expect(g.attrBottom, `attribution sous la barre (${label})`).toBeLessThanOrEqual(g.barTop - 2);
  expect(g.attrBottom, `attribution trop loin (${label})`).toBeGreaterThanOrEqual(g.barTop - 12);
}

async function creditBand(page) {
  return page.evaluate(() => {
    const attr = document.querySelector(".leaflet-control-attribution");
    const zoom = document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    const topLeft = document.querySelector(".leaflet-top.leaflet-left .leaflet-control-zoom");
    if (!attr || !zoom) return { ok: false };
    const as = getComputedStyle(attr);
    const zs = getComputedStyle(zoom);
    return {
      ok: true,
      attrBg: as.backgroundColor,
      zoomBg: zs.backgroundColor,
      attrText: (attr.textContent || "").replace(/\s+/g, " ").trim(),
      inTopLeft: Boolean(topLeft),
      inBottomRight: Boolean(zoom),
    };
  });
}

function expectTranslucentSlate(rgba, label) {
  expect(rgba, `${label} : couleur lisible`).toBeTruthy();
  expect(rgba.r, `${label} blanc opaque`).toBeLessThan(40);
  expect(rgba.g, `${label} blanc opaque`).toBeLessThan(50);
  expect(rgba.b, `${label} blanc opaque`).toBeLessThan(70);
  expect(rgba.a, `${label} trop opaque`).toBeLessThan(0.85);
  expect(rgba.a, `${label} invisible`).toBeGreaterThan(0.4);
}

async function placeDrawPoint(page, fracX, fracY) {
  const target = await page.evaluate(({ fx, fy }) => {
    const map = window.__naviguideScene?.map;
    if (!map) return null;
    const el = map.getContainer();
    const r = el.getBoundingClientRect();
    const x = r.left + r.width * fx;
    const y = r.top + r.height * fy;
    const latlng = map.containerPointToLatLng([x - r.left, y - r.top]);
    return { x, y, lat: latlng.lat, lng: latlng.lng };
  }, { fx: fracX, fy: fracY });
  expect(target, "carte pas prête pour poser un point").toBeTruthy();
  const before = await page.evaluate(() => window.__naviguideDrawn?.points?.length || 0);
  await page.mouse.click(target.x, target.y);
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => window.__naviguideDrawn?.points?.length || 0);
  if (after <= before) {
    await page.evaluate((ll) => {
      window.__naviguideScene.map.fire("click", { latlng: { lat: ll.lat, lng: ll.lng } });
    }, target);
  }
  await page.waitForFunction((n) => (window.__naviguideDrawn?.points?.length || 0) > n, before, { timeout: 8_000 });
  return target;
}

async function closestPin(page, x, y) {
  return page.evaluate(({ x: px, y: py }) => {
    const pins = [...document.querySelectorAll('[data-testid="waypoint-flag"]')];
    let best = null;
    for (const el of pins) {
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) continue;
      const cx = r.x + r.width / 2;
      const cy = r.y + r.height / 2;
      const d = Math.hypot(cx - px, cy - py);
      if (!best || d < best.d) best = { x: cx, y: cy, w: r.width, h: r.height, d };
    }
    return best;
  }, { x, y });
}

test("Crédits translucides, chevrons alignés, pin sous le clic", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — habillage carte autonome",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await leaveCinema(page);

  const closed = async () => {
    await setLeftPanel(page, false);
    await setRightPanel(page, false);
    await page.waitForTimeout(350);
    const t = await toggleTops(page);
    expect(t.delta, `chevrons fermés Δy=${t.delta}`).toBeLessThanOrEqual(1);
  };
  await closed();

  await setLeftPanel(page, true);
  await setRightPanel(page, true);
  await page.waitForTimeout(350);
  const opened = await toggleTops(page);
  expect(opened.delta, `chevrons ouverts Δy=${opened.delta}`).toBeLessThanOrEqual(1);

  const darkBand = await creditBand(page);
  expect(darkBand.ok, "crédits et zoom présents").toBeTruthy();
  expect(darkBand.inTopLeft, "zoom encore en haut à gauche").toBeFalsy();
  expect(darkBand.inBottomRight, "zoom en bas à droite").toBeTruthy();
  expect(darkBand.attrText).toMatch(/Leaflet/);
  expect(darkBand.attrText).toMatch(/Esri/);
  expect(darkBand.attrText).toMatch(/HERE/);
  expect(darkBand.attrText).toMatch(/Garmin/);
  expect(darkBand.attrText).toMatch(/OpenStreetMap/);
  expectTranslucentSlate(parseRgba(darkBand.attrBg), "crédits sombre");
  expectTranslucentSlate(parseRgba(darkBand.zoomBg), "zoom sombre");

  const theme = page.getByRole("button", { name: /^(sombre|dark)$/i });
  await expect(theme).toBeVisible({ timeout: 8_000 });
  await theme.click();
  await expect(page.locator(".light-mode")).toBeVisible({ timeout: 5_000 });

  const lightBand = await creditBand(page);
  expect(lightBand.ok).toBeTruthy();
  expect(lightBand.attrText).toBe(darkBand.attrText);
  expectTranslucentSlate(parseRgba(lightBand.attrBg), "crédits clair");
  expectTranslucentSlate(parseRgba(lightBand.zoomBg), "zoom clair");

  await closed();
  await assertAttributionOnBar(page, "clair, barre dépliée");
  const hide = page.getByTestId("hide-film-bar");
  await expect(hide).toBeVisible();
  await hide.click();
  await expect(page.getByTestId("show-film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "clair, barre repliée");
  await page.getByTestId("show-film-bar").click();
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "clair, barre dépliée après repli");
  await shot(page, "01-credits");

  const drawBtn = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i });
  await setLeftPanel(page, true);
  await expect(drawBtn).toBeVisible({ timeout: 15_000 });
  await drawBtn.scrollIntoViewIfNeeded();
  await drawBtn.click({ force: true });
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 15_000 });

  await setLeftPanel(page, false);
  await setRightPanel(page, false);
  await page.waitForTimeout(350);

  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    scene.userNavigated = true;
    scene.callbacks?.onManualNavigation?.();
    scene.map.setView([36, -20], 4, { animate: false });
  });
  await page.waitForTimeout(400);

  const mid = await placeDrawPoint(page, 0.52, 0.46);
  const pin1 = await closestPin(page, mid.x, mid.y);
  expect(pin1, "premier rond absent").toBeTruthy();
  expect(pin1.w, `rond 1 largeur ${pin1.w}`).toBeGreaterThanOrEqual(12);
  expect(pin1.w, `rond 1 largeur ${pin1.w}`).toBeLessThanOrEqual(16);
  expect(pin1.d, `premier rond à ${pin1.d.toFixed(1)} px du clic`).toBeLessThanOrEqual(3);

  await page.evaluate(() => {
    window.__naviguideScene.map.setZoom(8, { animate: false });
  });
  await page.waitForTimeout(400);

  const close = await placeDrawPoint(page, 0.68, 0.58);
  const pin2 = await closestPin(page, close.x, close.y);
  expect(pin2, "second rond absent").toBeTruthy();
  expect(pin2.d, `second rond à ${pin2.d.toFixed(1)} px du clic`).toBeLessThanOrEqual(3);
  await shot(page, "02-tracer");
});
