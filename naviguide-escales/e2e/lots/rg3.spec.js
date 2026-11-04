// AMP réelles et projets Blue Intelligence.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film / ici — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg3");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FISHING = /p[ée]toncles|deposit|chaluts|filets|hu[iî]tres|prohibition zone/i;
const REAL_AMP = /rochebonne|parc naturel marin|r[ée]serve|sanctuaire|agoa|tainui|mer de corail|scandola|cabrera|pertuis charentais(?!.*p[ée]toncles)/i;
const PROJECT = /le projet |project /i;

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

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

test("AMP réelles et projets BI, jamais une zone de pêche", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film/ici sautées ; barre et Revoir gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("replay-departure")).toBeVisible();

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }

  await expect(page.getByTestId("ici-maintenant")).toBeVisible();

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-amp");
    await shot(page, "02-projet");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG3 sautées",
    });
    await shot(page, "01-amp");
    await shot(page, "02-projet");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const hasRg2 = /eaux |cap au |waters |heading /i.test(blob);
  const hasAmp = REAL_AMP.test(blob);
  const hasProj = PROJECT.test(blob);
  if (!hasAmp && !hasProj) {
    if (hasRg2) {
      expect(hasAmp, "AMP réelle absente alors que le récit a déjà les eaux/cap RG2").toBeTruthy();
      expect(hasProj, "projet BI absent alors que le récit a déjà les eaux/cap RG2").toBeTruthy();
    }
    test.info().annotations.push({
      type: "film sans eaux RG2",
      description: "GET /voyage/official/film sans eaux/cap — assertions AMP/projet sautées",
    });
    await shot(page, "01-amp");
    await shot(page, "02-projet");
    return;
  }

  expect(blob, "jamais une zone de pêche dite AMP").not.toMatch(FISHING);

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 });

  await page.evaluate((reSrc) => {
    const list = window.__naviguideFilm?.chapters || [];
    const re = new RegExp(reSrc, "i");
    const i = list.findIndex((c) => re.test(c.text || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  }, REAL_AMP.source);
  await shot(page, "01-amp");

  await page.evaluate((reSrc) => {
    const list = window.__naviguideFilm?.chapters || [];
    const re = new RegExp(reSrc, "i");
    const i = list.findIndex((c) => re.test(c.text || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
  }, PROJECT.source);
  await shot(page, "02-projet");
});
