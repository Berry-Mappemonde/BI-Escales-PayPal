// L'avion est dit (aller et retour), le sous-titre de fin reste.
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// et la fin du film sont sautés. GET /voyage/official sondé ; s'il manque,
// annotation + saut des seules assertions avion / clôture — jamais Revoir
// retiré, ni les pilules, ni le champ date.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf5");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AIR = /prend l'avion pour Halifax|s'envole de Cayenne pour Halifax|retour en avion vers Cayenne|s['’]envole (?:de |d['’])Halifax pour Cayenne|the crew flies from Cayenne to Halifax|the crew flies to Halifax|return flight to Cayenne|flies from Halifax/i;
const CLOSE = /Aujourd[’']hui, le bateau est (à|en mer)/i;

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

test("Avion aller et retour, sous-titre de fin après l'arrêt", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  const officialBody = apiUp ? await official.json().catch(() => null) : null;
  const markBlob = JSON.stringify([
    ...((officialBody && officialBody.marks) || []),
    ...((officialBody && officialBody.escales) || []),
  ]);
  const routeHasAir = /cayenne/i.test(markBlob) && /halifax/i.test(markBlob);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — script avion / clôture sauté ; barre et Revoir gardés",
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

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("replay-departure")).toBeVisible();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-avion");
    await shot(page, "02-fin");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  expect(film?.chapters?.length, "GET /voyage/official/film?seconds=0 a des chapitres").toBeGreaterThan(0);

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  expect(film.targetSeconds, "sans case : pas de budget serveur").toBe(0);
  if (routeHasAir) {
    expect(blob, "avion aller").toMatch(/prend l'avion pour Halifax|s'envole de Cayenne pour Halifax|the crew flies from Cayenne to Halifax|the crew flies to Halifax/i);
    expect(blob, "avion retour").toMatch(/retour en avion vers Cayenne|s['’]envole (?:de |d['’])Halifax pour Cayenne|return flight to Cayenne|flies from Halifax/i);
  }
  expect(blob, "clôture dans le script").toMatch(CLOSE);
  expect(blob, "pas le seul départ Ajaccio").not.toMatch(/^[^.]*(départ vers Ajaccio)[^.]*$/i);

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await expect(subtitle).not.toHaveText("");

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 });

  const airIdx = await page.evaluate((reSrc) => {
    const re = new RegExp(reSrc, "i");
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => re.test(c.text || "") || /cayenne/i.test(c.fromName || "") || /cayenne/i.test(c.toName || ""));
    if (i >= 0) window.__naviguideFilm.seekChapter(i);
    return i;
  }, AIR.source);
  if (airIdx >= 0) {
    await expect(subtitle).toBeVisible();
  }
  await shot(page, "01-avion");

  const lastIdx = await page.evaluate((reSrc) => {
    const f = window.__naviguideFilm;
    const re = new RegExp(reSrc, "i");
    const list = f?.chapters || [];
    let idx = list.findIndex((c) => re.test(c.text || ""));
    if (idx < 0) idx = Math.max(0, (f.chapterCount || 1) - 1);
    f.seekChapter(idx);
    return idx;
  }, CLOSE.source);
  const closing = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const i = Number.isFinite(Number(f.chapterIdx)) ? Number(f.chapterIdx) : 0;
    const chapter = String(f.chapters?.[i]?.text || f.chapterText || "");
    const last = String(f.chapters?.[(f.chapters || []).length - 1]?.text || "");
    return { chapter, last };
  });
  expect(closing.chapter || closing.last, "chapitre de clôture").toMatch(CLOSE);
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const endIdx = await page.evaluate(() => window.__naviguideFilm?.chapterIdx);
  expect(endIdx, "dernière jambe").toBe(lastIdx);

  await page.evaluate(() => window.__naviguideFilm?.finishFilm?.());
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const after = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const list = f.chapters || [];
    return String(list[list.length - 1]?.text || f.chapterText || "");
  });
  expect(after, "clôture encore dans le script à l'arrêt").toMatch(CLOSE);
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await shot(page, "02-fin");
});
