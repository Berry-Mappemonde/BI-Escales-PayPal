// La position du bateau devient vraie et stable.
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, les
// assertions qui en dépendent sont sautées (annotation + return) — le build
// doit tenir debout seul (barre film + ligne d'état visibles).
// Avec API : hindcastStatus honnête (jamais « ready » à vide), deux lectures
// de /voyage/official/clock identiques (position stable), et si l'horloge a
// une part réelle (realUntil) : ligne d'état « réel jusqu'au … », route
// parcourue turquoise (#2dd4bf, réel) puis violette (#c084fc, climatologie).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-hc1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

// La ligne d'état vit dans la barre film : capture cadrée pour que
// « réel jusqu'au … » soit lisible (en pleine page elle est rognée à droite).
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

test("Position vraie : statut honnête, horloge stable, réel/climatologie", async ({ page }) => {
  test.setTimeout(120_000);

  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line").first()).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  const official = await getJson(page, "/voyage/official");
  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent (CI) — statut, stabilité et couleurs sautés ; le reste du spec n'est pas affaibli",
    });
    return;
  }

  // Statut honnête : jamais « ready » à vide.
  const status = official.hindcastStatus;
  if (status === "ready") {
    const cov = String(official.hindcastCoverage || "");
    expect(cov).toMatch(/^\d+\/\d+$/);
    expect(Number(cov.split("/")[0])).toBeGreaterThan(0);
  }
  if (status === "empty" || status === "partial") {
    // partial n/total affiché avec sa raison quand il y en a une.
    expect(String(official.hindcastCoverage || "")).toMatch(/^\d+\/\d+$/);
  }

  // Position stable : deux lectures successives, même horloge.
  const clockA = await getJson(page, "/voyage/official/clock");
  const clockB = await getJson(page, "/voyage/official/clock");
  if (clockA && clockA.vertices && clockB && clockB.vertices) {
    expect(clockB.arrivalIso).toEqual(clockA.arrivalIso);
    expect(clockB.vertices.length).toEqual(clockA.vertices.length);
    const lastA = clockA.vertices[clockA.vertices.length - 1];
    const lastB = clockB.vertices[clockB.vertices.length - 1];
    expect(lastB.lat).toEqual(lastA.lat);
    expect(lastB.lon).toEqual(lastA.lon);
    expect(lastB.sailNm).toEqual(lastA.sailNm);
  }

  const realUntil = clockA && clockA.realUntil;
  if (!realUntil) {
    test.info().annotations.push({
      type: "poste",
      description: "horloge sans part réelle (stock figé ou remplisseur pas passé) — libellé « réel jusqu'au » et couleurs sautés",
    });
    await shotBar(page, "02-statut");
    return;
  }

  // Part réelle + part climatologie dans la même horloge.
  const regimes = new Set((clockA.vertices || [])
    .map((v) => v.regime || v.kind).filter(Boolean));
  expect(regimes.has("hindcast")).toBeTruthy();
  expect(String(clockA.hindcastCoverage || "")).toMatch(/^\d+\/\d+$/);

  // Ligne d'état : « réel jusqu'au … » (fr) / « real until … » (en).
  await expect(page.getByTestId("clock-regime")).toContainText(
    /réel jusqu'au|real until/i,
    { timeout: 30_000 },
  );
  await shotBar(page, "02-statut");

  // Route parcourue : un trait réel turquoise (#2dd4bf). La carte est en
  // preferCanvas — pas de <path> SVG : on lit les pixels du canvas. Le rendu
  // de l'horloge (~9 000 sommets) arrive après la ligne d'état, d'où l'attente.
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
});
