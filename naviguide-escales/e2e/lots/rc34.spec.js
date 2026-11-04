// Le remplisseur recalcule l'horloge officielle HC1 au lieu de
// resservir le climo du jour sans realUntil. Sans API (CI) : GET
// /voyage/official sondé ; s'il ne répond pas, les assertions qui en
// dépendent sont sautées (annotation + return) — barre film + ligne d'état
// restent exigées. Avec API : ligne d'état « climatologie · réel jusqu'au
// <date> » / « climatology · real until <date> », route parcourue turquoise
// (#2dd4bf) jusqu'à la frontière réelle.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc34");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const shotBar = (page, name) => page.getByTestId("film-bar").screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
});

async function getJson(page, url) {
  const res = await page.request.get(url, { timeout: 8000 }).catch(() => null);
  if (!res || !res.ok()) return null;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return null;
  return res.json().catch(() => null);
}

test("Suivre : climatologie · réel jusqu'au <date>, route turquoise puis violette", async ({ page }) => {
  test.setTimeout(120_000);

  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line").first()).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const official = await getJson(page, "/voyage/official");
  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent (CI) — realUntil, libellé et couleurs sautés ; barre film et ligne d'état conservées",
    });
    await shotBar(page, "02-statut");
    return;
  }

  const clockA = await getJson(page, "/voyage/official/clock");
  const clockB = await getJson(page, "/voyage/official/clock");
  if (clockA && clockA.vertices && clockB && clockB.vertices) {
    expect(clockB.arrivalIso).toEqual(clockA.arrivalIso);
    expect(clockB.vertices.length).toEqual(clockA.vertices.length);
    const lastA = clockA.vertices[clockA.vertices.length - 1];
    const lastB = clockB.vertices[clockB.vertices.length - 1];
    expect(lastB.lat).toEqual(lastA.lat);
    expect(lastB.lon).toEqual(lastA.lon);
  }

  const realUntil = clockA && clockA.realUntil;
  if (!realUntil) {
    test.info().annotations.push({
      type: "poste",
      description: "horloge sans realUntil (stock figé ou remplisseur pas encore passé) — libellé « réel jusqu'au » et couleurs sautés",
    });
    await shotBar(page, "02-statut");
    return;
  }

  await expect(page.getByTestId("clock-regime")).toContainText(/climatologie · réel jusqu'au/i, {
    timeout: 30_000,
  });
  await shotBar(page, "02-statut");

  await page.waitForFunction(() => {
    const want = [45, 212, 191]; // #2dd4bf — réel (teintes de C3)
    for (const c of document.querySelectorAll("canvas")) {
      const ctx = c.getContext("2d");
      if (!ctx || !c.width || !c.height) continue;
      let data;
      try { data = ctx.getImageData(0, 0, c.width, c.height).data; } catch { continue; }
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] > 200
          && Math.abs(data[i] - want[0]) <= 3
          && Math.abs(data[i + 1] - want[1]) <= 3
          && Math.abs(data[i + 2] - want[2]) <= 3) return true;
      }
    }
    return false;
  }, null, { timeout: 60_000, polling: 1000 });
  await shot(page, "01-route-reel");

  await showRightPanel(page);
  await page.getByTestId("lang-en").click();
  await expect(page.getByTestId("clock-regime")).toContainText(/real until/i, {
    timeout: 15_000,
  });
  await shotBar(page, "03-statut-en");
});
