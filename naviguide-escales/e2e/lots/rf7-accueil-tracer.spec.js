// Accueil Suivre + Cinéma + monde dézoomé ; Tracer monde + dézoom libre.
// Accueil et clic Suivre = bateau au centre, zoom = plancher
// (plus de zoom > 3). Sans API : montage (Suivre, Cinéma, zoom plancher,
// panneaux fermés) et Tracer (vue monde, dézoom jusqu'au monde) tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent (bateau au centre) — jamais le mode initial,
// ni le Cinéma, ni les panneaux, ni le dézoom Tracer.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, mapFollowCadrage } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf7");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

function cinemaButton(page) {
  return page.getByRole("button", { name: /^(cinéma|cinema)$/i });
}

async function cinemaPressed(page) {
  return /bg-cyan-700/.test((await cinemaButton(page).getAttribute("class")) || "");
}

async function panelClosed(page, side) {
  const loc = side === "left"
    ? page.locator(".naviguide-sidebar-panel.left-0").first()
    : page.locator(".naviguide-sidebar-panel.right-0").first();
  const cls = (await loc.getAttribute("class")) || "";
  return cls.includes("translate-x-full");
}

async function mapZoom(page) {
  return page.evaluate(() => window.__naviguideScene?.map?.getZoom?.() ?? null);
}

async function enterTracer(page) {
  // La pilule Tracer ouvre le dessin (vue monde).
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  if (await panelClosed(page, "left")) {
    await page.locator(".naviguide-sidebar-toggle--left").click();
    await expect.poll(() => panelClosed(page, "left"), { timeout: 8_000 }).toBe(false);
  }
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 10_000 });
}

test("Accueil Suivre cinéma monde ; clic Suivre recadre ; Tracer dézoome", async ({ page }) => {
  test.setTimeout(90_000);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const official = await page.request.get("/voyage/official", { timeout: 2500 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — bateau au centre sauté ; zoom plancher et Tracer conservés",
    });
  }

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "false");
  await expect(cinemaButton(page)).toBeVisible();
  expect(await cinemaPressed(page), "Cinéma enfoncé au chargement").toBe(true);
  await expect.poll(() => panelClosed(page, "left"), { timeout: 8_000 }).toBe(true);
  await expect.poll(() => panelClosed(page, "right"), { timeout: 8_000 }).toBe(true);

  const mapReady = await page.waitForFunction(() => window.__naviguideScene?.map, null, { timeout: 15_000 })
    .then(() => true)
    .catch(() => false);
  if (mapReady) {
    await expect.poll(async () => {
      const z = await mapZoom(page);
      return Number.isFinite(z) ? z : 99;
    }, { timeout: 8_000 }).toBeGreaterThanOrEqual(2.4);
    await expect.poll(async () => {
      const z = await mapZoom(page);
      return Number.isFinite(z) ? z : 99;
    }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);
    if (apiUp) {
      await page.waitForTimeout(1200);
      const zHold = await mapZoom(page);
      expect(zHold, "plancher RC18 (monde une fois), cadrage bateau sans zoom-in").toBeGreaterThanOrEqual(2.4);
      expect(zHold, "plancher RC18 (monde une fois), cadrage bateau sans zoom-in").toBeLessThanOrEqual(2.6);
      await expect.poll(async () => {
        const s = await mapFollowCadrage(page);
        return Number.isFinite(s?.boatPx) ? s.boatPx : 9999;
      }, { timeout: 15_000 }).toBeLessThan(80);
    }
    const minZ = await page.evaluate(() => window.__naviguideScene.map.getMinZoom());
    expect(minZ, "plancher RC18").toBeLessThanOrEqual(2.6);
  }

  await shot(page, "01-accueil");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => cinemaPressed(page), { timeout: 8_000 }).toBe(false);
  await expect.poll(() => panelClosed(page, "left"), { timeout: 10_000 }).toBe(false);
  await expect.poll(() => panelClosed(page, "right"), { timeout: 10_000 }).toBe(false);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  expect(await cinemaPressed(page), "clic Suivre : Cinéma enfoncé").toBe(true);
  await expect.poll(() => panelClosed(page, "left"), { timeout: 8_000 }).toBe(true);
  await expect.poll(() => panelClosed(page, "right"), { timeout: 8_000 }).toBe(true);

  if (apiUp && mapReady) {
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.zoom) ? s.zoom : 99;
    }, { timeout: 8_000 }).toBeGreaterThanOrEqual(2.4);
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.zoom) ? s.zoom : 99;
    }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.boatPx) ? s.boatPx : 9999;
    }, { timeout: 15_000 }).toBeLessThan(80);
  }

  await enterTracer(page);
  if (mapReady) {
    await expect.poll(async () => {
      const z = await mapZoom(page);
      return Number.isFinite(z) ? z : 99;
    }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);

    await page.evaluate(() => {
      window.__naviguideScene.map.setView([22, 5], 5, { animate: false });
    });
    await page.waitForTimeout(200);
    const box = await page.locator(".leaflet-container").boundingBox();
    expect(box).toBeTruthy();
    await page.mouse.move(box.x + box.width * 0.72, box.y + box.height * 0.42);
    for (let i = 0; i < 16; i += 1) await page.mouse.wheel(0, 240);
    await expect.poll(async () => {
      const z = await mapZoom(page);
      return Number.isFinite(z) ? z : 99;
    }, { timeout: 8_000 }).toBeLessThanOrEqual(2.6);
  }

  await shot(page, "02-tracer");
});
