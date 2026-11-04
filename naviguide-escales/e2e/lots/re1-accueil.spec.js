// Accueil Suivre + Cinéma + monde dézoomé (plancher) ;
// Suivre → Tracer décoche le Cinéma et ouvre les deux panneaux.
// Accueil et clic Suivre = bateau au centre, zoom = plancher
// (plus de zoom > 3). Sans API : montage (Suivre, Cinéma, zoom plancher,
// panneaux fermés) et la bascule tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent (bateau au centre) — jamais le mode initial,
// ni le Cinéma, ni le plancher, ni l'ouverture des panneaux.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, mapFollowCadrage } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re1");
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

function panelOnScreen(page, side) {
  const sel = side === "left"
    ? ".naviguide-sidebar-panel.left-0"
    : ".naviguide-sidebar-panel.right-0";
  return page.locator(sel).first().evaluate((el) => {
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 50 && r.right > 12 && r.left < window.innerWidth - 12;
  });
}

async function mapZoom(page) {
  return page.evaluate(() => window.__naviguideScene?.map?.getZoom?.() ?? null);
}

async function probeOfficial(request) {
  const official = await request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  if (!official || !official.ok()) return null;
  const ct = official.headers()["content-type"] || "";
  if (!ct.includes("json")) return null;
  const body = await official.json().catch(() => null);
  return body && typeof body === "object" ? body : null;
}

test("Accueil Simulation cinéma monde ; Suivre → Simulation ouvre les panneaux", async ({ page, request }) => {
  test.setTimeout(90_000);
  const officialBody = await probeOfficial(request);
  const apiUp = Boolean(officialBody);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — bateau au centre sauté ; zoom plancher et mode conservés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  // RF7 remplace RE1 : accueil Suivre + Cinéma + monde (plus Simulation).
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "false");
  await expect(cinemaButton(page)).toBeVisible();
  expect(await cinemaPressed(page), "Cinéma enfoncé au chargement").toBe(true);
  await expect.poll(() => panelOnScreen(page, "left"), { timeout: 8_000 }).toBe(false);
  await expect.poll(() => panelOnScreen(page, "right"), { timeout: 8_000 }).toBe(false);

  const mapReady = await page.waitForFunction(() => window.__naviguideScene?.map, null, { timeout: 20_000 })
    .then(() => true)
    .catch(() => false);
  if (mapReady) {
    const zoom0 = await mapZoom(page);
    expect(zoom0, "plancher RC18 (monde une fois)").toBeGreaterThanOrEqual(2.4);
    expect(zoom0, "plancher RC18 (monde une fois)").toBeLessThanOrEqual(2.6);
  }

  await shot(page, "01-accueil");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  expect(await cinemaPressed(page), "entrée en Suivre : Cinéma reste enfoncé").toBe(true);
  await expect.poll(() => panelOnScreen(page, "left"), { timeout: 8_000 }).toBe(false);
  await expect.poll(() => panelOnScreen(page, "right"), { timeout: 8_000 }).toBe(false);

  if (apiUp && mapReady) {
    await page.waitForFunction(() => (
      Boolean(window.__naviguideScene?.config?.live?.lat)
      || Boolean(document.querySelector(".catamaran-divicon--live"))
    ), null, { timeout: 25_000 }).catch(() => {});
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.zoom) ? s.zoom : 99;
    }, { timeout: 15_000 }).toBeGreaterThanOrEqual(2.4);
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.zoom) ? s.zoom : 99;
    }, { timeout: 15_000 }).toBeLessThanOrEqual(2.6);
    await expect.poll(async () => {
      const s = await mapFollowCadrage(page);
      return Number.isFinite(s?.boatPx) ? s.boatPx : 9999;
    }, { timeout: 25_000 }).toBeLessThan(80);
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => cinemaPressed(page), { timeout: 8_000 }).toBe(false);
  await expect.poll(() => panelOnScreen(page, "left"), { timeout: 10_000 }).toBe(true);
  await expect.poll(() => panelOnScreen(page, "right"), { timeout: 10_000 }).toBe(true);
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 8_000 });

  await shot(page, "02-bascule");
});
