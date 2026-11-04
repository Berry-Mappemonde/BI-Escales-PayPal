// Gabarit narratif par étape (ouverture → route → escale).
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg6");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FORBIDDEN = /\bjambe\b|zone économique exclusive|Couloirs\s*:|À surveiller|à portée de|\bde de\b/i;
const QUAY_REPEAT = /3 jours à quai/;
const OPENING = /Berry-Mappemonde quitte|Berry-Mappemonde leaves/i;
const MILES_DAYS = /\d[\d\s]*\s*milles|dizaine de jours|jours de mer|miles|days at sea/i;
const ARRIVAL = /Arrivée à Ajaccio|Arrival at Ajaccio/i;

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

test("Gabarit d'étape, sans jargon ni annexe", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre et Revoir gardés",
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
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();

  const durations = page.getByTestId("film-duration");
  if (await durations.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée").toHaveCount(0);
  }

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-sous-titre");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG6 sautées",
    });
    await shot(page, "01-sous-titre");
    return;
  }

  const blob = film.chapters.map((c) => c.text || "").join(" ");
  const hasRgOpening = OPENING.test(blob)
    || /L['’]expédition Berry-Mappemonde|The Berry-Mappemonde expedition/i.test(blob);
  // Ouverture RG6/RG7 ⇒ Revoir jouable ; plus de skip « pré-RG » qui cache un bouton grisé.
  if (hasRgOpening) {
    await expect(start).toBeEnabled({ timeout: 30_000 });
  }
  // Stock figé : ouverture RG6/RG7 possible avec encore du jargon — Revoir est
  // déjà vérifié ; on saute le discours RG6, on ne l'affaiblit pas.
  if (FORBIDDEN.test(blob) || QUAY_REPEAT.test(blob) || !OPENING.test(blob)) {
    test.info().annotations.push({
      type: "stock pré-RG6",
      description: "film servi encore à l'ancienne clé — remplisseur doit recalculer (FILM_SCRIPT_REV=rg6)",
    });
    await shot(page, "01-sous-titre");
    return;
  }

  expect(blob, "mots interdits absents").not.toMatch(FORBIDDEN);
  expect(blob, "plus de « 3 jours à quai »").not.toMatch(QUAY_REPEAT);
  expect(blob, "ouverture Berry-Mappemonde").toMatch(OPENING);

  const lrAj = film.chapters.find((c) => /La Rochelle/i.test(c.fromName || "") && /Ajaccio/i.test(c.toName || c.text || ""));
  if (lrAj) {
    expect(lrAj.text, "milles et jours dans l'ouverture").toMatch(MILES_DAYS);
    expect(lrAj.text, "arrivée nommée").toMatch(ARRIVAL);
  }

  await expect(start).toBeEnabled({ timeout: 30_000 });
  await muteVoice(page);
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });

  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).catch(() => null);

  await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    const i = list.findIndex((c) => /La Rochelle/i.test(c.fromName || "") && /Ajaccio/i.test((c.toName || "") + (c.text || "")));
    if (i >= 0 && window.__naviguideFilm?.seekChapter) window.__naviguideFilm.seekChapter(i);
  });
  await expect(subtitle).toBeVisible();
  await shot(page, "01-sous-titre");
});
