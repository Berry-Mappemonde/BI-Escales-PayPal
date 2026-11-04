// GET /film sert le script RF5 (avion aller et retour).
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions avion — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc13");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const AIR_OUT = /prend l'avion pour|s'envole de Cayenne|the crew flies (?:to|from)/i;
const AIR_BACK = /retour en avion vers|return flight to|s['’]envole (?:de |d['’])Halifax|flies from Halifax/i;

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

async function waitOfficialFilm(page) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < 20_000) {
    const r = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
      .then((x) => (x.ok() ? x.json() : null))
      .catch(() => null);
    last = r;
    if (r?.chapters?.length && r.status !== "preparing") return r;
    await page.waitForTimeout(800);
  }
  return last;
}

test("GET /film dit l'avion aller et retour si Cayenne et Halifax", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  const officialBody = apiUp ? await official.json().catch(() => null) : null;
  const markBlob = JSON.stringify([
    ...((officialBody && officialBody.marks) || []),
    ...((officialBody && officialBody.escales) || []),
  ]);
  const routeHasCayenne = /cayenne/i.test(markBlob);
  const routeHasAir = routeHasCayenne && /halifax/i.test(markBlob);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions avion sautées ; Suivre et Revoir gardés",
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
    await expect(page.getByTestId("replay-departure")).toBeVisible();
    await shot(page, "01-avion");
    return;
  }

  const film = await waitOfficialFilm(page);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film en préparation",
      description: "GET /voyage/official/film sans chapitres — assertions avion sautées",
    });
    await shot(page, "01-avion");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  expect(film.targetSeconds, "sans case : pas de budget serveur").toBe(0);
  // Marques officielles : Cayenne + Halifax. Ou Cayenne en marques et Halifax
  // déjà dans le script calculé depuis l'itinéraire Berry (route.geojson).
  if (routeHasAir || (routeHasCayenne && /halifax/i.test(blob))) {
    expect(blob, "avion aller").toMatch(AIR_OUT);
    expect(blob, "avion retour").toMatch(AIR_BACK);
  }

  if (await start.isEnabled().catch(() => false)) {
    await muteVoice(page);
    await start.click();
    await muteVoice(page);
    const subtitle = page.getByTestId("film-subtitle");
    await expect(subtitle).toBeVisible({ timeout: 8_000 });
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
    }, null, { timeout: 8_000 }).catch(() => null);
    // SeekChapter(i) sans caractère épinglé va en fin de jambe, puis
    // le tick passe au chapitre « Aujourd'hui ». L'avion est au milieu de
    // Cayenne → Saint-Pierre — viser la phrase, pas seulement l'index.
    const airIdx = await page.evaluate(() => {
      const re = /prend l'avion|s'envole|retour en avion|the crew flies|return flight/i;
      const list = window.__naviguideFilm?.chapters || [];
      for (const chapter of list) {
        const text = chapter.text || "";
        const at = text.search(re);
        if (at < 0) continue;
        const i = Number.isFinite(Number(chapter.idx)) ? Number(chapter.idx) : list.indexOf(chapter);
        window.speechSynthesis?.cancel?.();
        window.__naviguideFilm?.seekChapter?.(i, at);
        return i;
      }
      return -1;
    });
    if (airIdx >= 0) {
      await expect(subtitle).toContainText(/avion|s'envole|flies/i, { timeout: 8_000 });
    }
  }
  await shot(page, "01-avion");
});
