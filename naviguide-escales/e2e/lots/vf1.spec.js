// La voix coincée ne fige plus le film.
// Sans API : GET /voyage/official sondé ; s'il manque, annotation + saut des
// assertions lecture — barre et Revoir restent vérifiés.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-vf1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  const t0 = Date.now();
  const res = await page.request.get("/voyage/official", { timeout: 20_000 }).catch(() => null);
  const ms = Date.now() - t0;
  if (!res || !res.ok()) return { apiUp: false, ms };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false, ms };
  return { apiUp: true, ms };
}

const LA_ROCHELLE = { lat: 46.154, lon: -1.167 };

function filmSnapshot() {
  const f = window.__naviguideFilm || {};
  return {
    chapterIdx: Number.isFinite(Number(f.chapterIdx)) ? Number(f.chapterIdx) : 0,
    charIdx: Number.isFinite(Number(f.charIdx)) ? Number(f.charIdx) : 0,
    elapsed: Number(f.elapsed) || 0,
    lat: Number.isFinite(Number(f.lat)) ? Number(f.lat) : null,
    lon: Number.isFinite(Number(f.lon)) ? Number(f.lon) : null,
    bubbleKind: f.bubbleKind || null,
    ended: Boolean(f.ended),
  };
}

function leftLaRochelle(snap) {
  if (!snap || snap.ended) return false;
  if (snap.chapterIdx > 0) return true;
  const { lat, lon, charIdx } = snap;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  const dlat = lat - LA_ROCHELLE.lat;
  const dlon = lon - LA_ROCHELLE.lon;
  return charIdx > 231 && (dlat * dlat + dlon * dlon) > 0.25;
}

async function waitPastLaRochelle(page, timeout = 90_000) {
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm || {};
    if (f.ended) return false;
    const idx = Number(f.chapterIdx);
    if (Number.isFinite(idx) && idx > 0) return true;
    const lat = Number(f.lat);
    const lon = Number(f.lon);
    const charIdx = Number(f.charIdx) || 0;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    const dlat = lat - 46.154;
    const dlon = lon - (-1.167);
    return charIdx > 231 && (dlat * dlat + dlon * dlon) > 0.25;
  }, null, { timeout });
}

test("Deuxième Revoir sans rechargement : le bateau quitte La Rochelle", async ({ page }) => {
  test.setTimeout(240_000);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("replay-departure")).toBeVisible();

  const { apiUp, ms: probeMs } = await probeOfficial(page);
  if (!apiUp && probeMs < 2000 && !(await start.isEnabled())) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions lecture sautées ; barre et Revoir gardés",
    });
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    return;
  }

  const canPlay = await waitFilmCanStart(page, 30_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: apiUp ? "Revoir grisé" : "sans API",
      description: apiUp
        ? "film officiel pas prêt — lectures sautées ; barre et Revoir gardés"
        : "GET /voyage/official absent — assertions lecture sautées ; barre et Revoir gardés",
    });
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    return;
  }

  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await waitPastLaRochelle(page);
  const firstPlay = await page.evaluate(filmSnapshot);
  expect(firstPlay.ended, "la première lecture ne se termine pas à La Rochelle").toBe(false);
  expect(leftLaRochelle(firstPlay), "première lecture : hors de La Rochelle (chapterIdx > 0 ou bateau parti)").toBeTruthy();

  await page.getByTestId("replay-stop").click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });

  await page.getByTestId("replay-start").click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await waitPastLaRochelle(page);
  const secondA = await page.evaluate(filmSnapshot);
  expect(secondA.ended, "la deuxième lecture ne se termine pas").toBe(false);
  expect(leftLaRochelle(secondA), "deuxième lecture sans rechargement : hors de La Rochelle").toBeTruthy();

  await page.waitForTimeout(10_000);
  const secondB = await page.evaluate(filmSnapshot);
  expect(secondB.ended, "10 s plus tard le film n'est pas fini").toBe(false);
  expect(secondB.charIdx, "charIdx a augmenté sur la deuxième lecture").toBeGreaterThan(secondA.charIdx);

  writeFileSync(
    join(recetteDir, "releves-deuxieme-lecture.json"),
    `${JSON.stringify({ a: secondA, b: secondB }, null, 2)}\n`,
  );
  await shot(page, "01-deuxieme-lecture");
});
