// Récit officiel, pas le film Simulation.
// Sans API : Revoir visible et non cliquable, champ date là, pas de récit
// Ajaccio. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions du script serveur — jamais Revoir retiré, ni le champ
// date, ni les asserts hors API.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-re7");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FORBIDDEN = /station croisée\s*:\s*Station croisée|Aucun port d'entr[ée]e|entrée dans Entrée dans/i;
const LAST_LEG = /Aujourd[’']hui, le bateau est (à|en mer)/i;
const GEO = /golfe de Gascogne|détroit de Gibraltar|Gibraltar/i;

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

function wordCount(text) {
  return (String(text || "").match(/\S+/g) || []).length;
}

const RG6_OPENING = /Berry-Mappemonde quitte|L['’]expédition Berry-Mappemonde|Berry-Mappemonde leaves|The Berry-Mappemonde expedition/i;
const RG6_MILES_DAYS = /milles|jours de mer|days at sea|\bmiles\b/i;
const RG7_CLOSE = /Aujourd['’]hui, le bateau|Today, the boat/i;

function hasRg6Rg7Fingerprint(blob) {
  if (RG7_CLOSE.test(blob)) return true;
  return RG6_OPENING.test(blob) && RG6_MILES_DAYS.test(blob);
}

function isRe7Film(free) {
  const chapters = free?.chapters || [];
  if (!chapters.length) return false;
  const blob = chapters.map((c) => c.text || "").join(" ");
  if (FORBIDDEN.test(blob)) return false;
  if (/milles nautiques du départ|Bay of Biscay/.test(blob)) return false;
  // Un film RG6+ long n'est pas stale pour le seul plafond 800.
  if (wordCount(blob) > 800 && !hasRg6Rg7Fingerprint(blob)) return false;
  return true;
}

async function waitRe7Film(page, { timeout = 45_000 } = {}) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    const free = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    if (free?.chapters?.length) {
      last = free;
      if (isRe7Film(free)) return { film: free, stale: false };
      return { film: free, stale: true };
    }
    await page.waitForTimeout(800);
  }
  return last ? { film: last, stale: !isRe7Film(last) } : null;
}

test("Récit sans durée, un lieu une fois, dernière jambe fermée", async ({ page }) => {
  test.setTimeout(120_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — script serveur /film sauté",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    const pressed = durations.locator("[aria-pressed='true']");
    await expect(pressed, "aucune durée cochée").toHaveCount(0);
  }

  if (!apiUp) {
    const start = page.getByTestId("replay-start");
    await expect(start).toBeVisible({ timeout: 15_000 });
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("replay-departure")).toBeVisible();
    await expect(durations).toHaveCount(0);
    await expect(page.getByTestId("replay-stop")).toHaveCount(0);
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    const started = await page.evaluate(() => Boolean(window.__naviguideFilm?.startedAt));
    expect(started, "pas de film Simulation sans /film").toBe(false);
    return;
  }

  const probed = await waitRe7Film(page);
  expect(probed?.film?.chapters?.length, "GET /film?seconds=0 a des chapitres").toBeGreaterThan(0);
  expect(probed.stale, "film figé RE7 / RC17 (même checkout)").toBe(false);

  const free = probed.film;
  const blob = free.chapters.map((c) => c.text || "").join(" ");
  expect(free.targetSeconds, "sans case : pas de budget serveur").toBe(0);
  expect(blob, "pas de station sans nom").not.toMatch(/station croisée\s*:\s*Station croisée/i);
  expect(blob, "pas d'absence racontée").not.toMatch(/Aucun port d'entr[ée]e/i);
  expect(blob, "pas d'entrée doublée").not.toMatch(/entrée dans Entrée dans/i);
  expect(blob, "géographie officielle").toMatch(GEO);
  const last = free.chapters[free.chapters.length - 1]?.text || "";
  expect(last, "dernière jambe fermée").toMatch(LAST_LEG);
  if (/halifax/i.test(blob) && /cayenne|guyane/i.test(blob)) {
    expect(blob, "avion dit").toMatch(/avion|équipage prend|s['’]envole|flies/i);
  }

  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 30_000 });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  if (await durations.isVisible().catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }
  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const sub = (await subtitle.innerText()).trim();
  expect(sub, "sous-titre non vide").not.toBe("");
  expect(sub, "pas de phrase interdite dans le sous-titre").not.toMatch(FORBIDDEN);
  expect(sub, "récit officiel en tête").toMatch(/Saint-Maur/);
  await shot(page, "01-recit");

  const budgetNone = await page.evaluate(() => window.__naviguideFilm?.budgetSeconds);
  expect(budgetNone, "aucune durée → pas de budget").toBe(0);

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 });
  const lastIdx = await page.evaluate(() => {
    const f = window.__naviguideFilm;
    const idx = Math.max(0, (f.chapterCount || 1) - 1);
    f.seekChapter(idx);
    return idx;
  });
  const lastChapter = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const list = f.chapters || [];
    const i = Number.isFinite(Number(f.chapterIdx)) ? Number(f.chapterIdx) : list.length - 1;
    return String(list[i]?.text || list[list.length - 1]?.text || f.chapterText || "");
  });
  expect(lastChapter, "dernière jambe fermée à l'écran").toMatch(LAST_LEG);
  await expect(subtitle).toBeVisible();
  const endIdx = await page.evaluate(() => window.__naviguideFilm?.chapterIdx);
  expect(endIdx, "02-fin à la dernière jambe").toBe(lastIdx);
  await shot(page, "02-fin");

  const stopBtn = page.getByTestId("replay-stop");
  if (await stopBtn.isVisible().catch(() => false)) await stopBtn.click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
});
