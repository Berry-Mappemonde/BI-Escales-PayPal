// Crédits Leaflet collés juste au-dessus de la barre film,
// même hauteur que les boutons + / − (revue du 14 oct.).
// Sans API : géométrie attribution / zoom / barre film autonome.
// GET /voyage/official sondé ; s'il manque, annotation seulement
// (aucune assertion n'en dépend).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-ui1");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

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

async function creditGeometry(page) {
  return page.evaluate(() => {
    const attr = document.querySelector(".leaflet-control-attribution");
    const zoom = document.querySelector(".leaflet-bottom.leaflet-right .leaflet-control-zoom");
    const plus = document.querySelector(".leaflet-control-zoom-in");
    const chrome = document.querySelector("[data-testid='film-bar']")
      || document.querySelector("[data-testid='show-film-bar']");
    if (!attr || !zoom || !chrome) return { ok: false };
    const a = attr.getBoundingClientRect();
    const z = zoom.getBoundingClientRect();
    const p = plus?.getBoundingClientRect();
    const b = chrome.getBoundingClientRect();
    return {
      ok: true,
      attrH: a.height,
      zoomH: z.height,
      plusH: p?.height ?? 0,
      attrBottom: a.bottom,
      barTop: b.top,
      gap: b.top - a.bottom,
      text: (attr.textContent || "").replace(/\s+/g, " ").trim(),
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
  expect(g.ok, `crédits/zoom/barre (${label})`).toBeTruthy();
  expect(Math.abs(g.attrH - g.zoomH), `hauteur attribution ${g.attrH} vs zoom ${g.zoomH} (${label})`).toBeLessThanOrEqual(0.5);
  expect(Math.abs(g.attrH - g.plusH), `hauteur attribution ${g.attrH} vs + ${g.plusH} (${label})`).toBeLessThanOrEqual(0.5);
  expect(g.attrBottom, `attribution sous la barre (${label}), gap=${g.gap}`).toBeLessThanOrEqual(g.barTop - 2);
  expect(g.attrBottom, `attribution trop loin de la barre (${label}), gap=${g.gap}`).toBeGreaterThanOrEqual(g.barTop - 12);
  expect(g.text).toMatch(/Leaflet/);
  expect(g.text).toMatch(/Esri/);
  expect(g.text).toMatch(/OpenStreetMap/);
}

test("Attribution collée à la barre film, même hauteur que + / −", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — géométrie crédits / zoom / barre autonome",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 });
  await leaveCinema(page);

  await setLeftPanel(page, false);
  await setRightPanel(page, false);
  await assertAttributionOnBar(page, "sombre, panneaux fermés, barre dépliée");

  await setLeftPanel(page, true);
  await setRightPanel(page, true);
  await assertAttributionOnBar(page, "sombre, panneaux ouverts, barre dépliée");

  const hide = page.getByTestId("hide-film-bar");
  await expect(hide).toBeVisible();
  await hide.click();
  await expect(page.getByTestId("show-film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "sombre, barre repliée");

  await page.getByTestId("show-film-bar").click();
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "sombre, barre dépliée après repli");

  const theme = page.getByRole("button", { name: /^(sombre|dark)$/i });
  await expect(theme).toBeVisible({ timeout: 8_000 });
  await theme.click();
  await expect(page.locator(".light-mode")).toBeVisible({ timeout: 5_000 });

  await setLeftPanel(page, false);
  await setRightPanel(page, false);
  await assertAttributionOnBar(page, "clair, panneaux fermés, barre dépliée");

  await hide.click();
  await expect(page.getByTestId("show-film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "clair, barre repliée");

  await page.getByTestId("show-film-bar").click();
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 5_000 });
  await assertAttributionOnBar(page, "clair, barre dépliée");

  await setLeftPanel(page, true);
  await setRightPanel(page, true);
  await assertAttributionOnBar(page, "clair, panneaux ouverts");

  await setLeftPanel(page, false);
  await setRightPanel(page, false);
  await assertAttributionOnBar(page, "clair, capture");
  await shot(page, "01-attribution");
});
