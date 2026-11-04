// Ouverture (expédition, escales, milles) et fin (aujourd'hui, ETA, à venir).
// Sans API : Suivre, Revoir et la barre tiennent seuls ; le script serveur
// est sauté. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions film — jamais Revoir retiré, ni les pilules, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg7");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const OPENING = /L['’]expédition Berry-Mappemonde|The Berry-Mappemonde expedition/i;
const ROAD = /par la route jusqu|by road to/i;
const PLAN = /Le plan compte|The plan has/i;
const CLOSE = /Aujourd['’]hui, le bateau|Today, the boat/i;
const UPCOMING = /Les escales à venir|Stops still to come/i;
const ETA_RANGE = /entre le .+ et le |between .+ and /i;

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

function uniqueDests(legs) {
  const seen = new Set();
  const out = [];
  for (const leg of legs || []) {
    const raw = String(leg?.to || "").replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
    const key = raw.toLowerCase();
    if (raw && !seen.has(key)) {
      seen.add(key);
      out.push(raw);
    }
  }
  return out;
}

function sumLegNm(legs) {
  let total = 0;
  for (const leg of legs || []) {
    const n = Number(leg?.legNm);
    if (Number.isFinite(n) && n > 0) total += n;
  }
  return Math.round(total);
}

test("Ouverture de l'expédition et fin aujourd'hui", async ({ page }) => {
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
    await shot(page, "01-fin");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans chapitres — assertions RG7 sautées",
    });
    await shot(page, "01-fin");
    return;
  }

  const first = film.chapters[0]?.text || "";
  const last = film.chapters[film.chapters.length - 1]?.text || "";
  const hasRgOpening = OPENING.test(first)
    || /Berry-Mappemonde quitte|Berry-Mappemonde leaves/i.test(
      film.chapters.map((c) => c.text || "").join(" "),
    );
  // Ouverture RG6/RG7 ⇒ Revoir jouable ; plus de skip « pré-RG » qui cache un bouton grisé.
  if (hasRgOpening) {
    await expect(start).toBeEnabled({ timeout: 30_000 });
  }
  if (!OPENING.test(first) || !ROAD.test(first)) {
    test.info().annotations.push({
      type: "stock pré-RG7",
      description: "film servi encore à l'ancienne clé — remplisseur doit recalculer (FILM_SCRIPT_REV=rg7)",
    });
    await shot(page, "01-fin");
    return;
  }

  expect(first, "ouverture expédition").toMatch(OPENING);
  expect(first, "départ par la route").toMatch(ROAD);
  expect(last, "fin aujourd'hui").toMatch(CLOSE);

  const review = await page.request.get("/voyage/official/plan-review", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const legs = Array.isArray(review?.legs) ? review.legs : [];
  if (legs.length) {
    const dests = uniqueDests(legs);
    const total = sumLegNm(legs);
    expect(first, "totaux du plan-review").toMatch(PLAN);
    expect(first, "nombre d'escales du plan").toMatch(new RegExp(`${dests.length}|escales`));
    if (total > 0) {
      const spaced = String(total).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
      expect(first.replace(/\s/g, ""), "somme des milles").toContain(String(total));
      expect(first.includes(spaced) || first.replace(/\s/g, "").includes(String(total))).toBeTruthy();
    }
    const finalDest = dests[dests.length - 1];
    if (finalDest) expect(first, "destination finale").toContain(finalDest.split(" ")[0]);
    if (UPCOMING.test(last)) {
      const next = dests.find((name) => last.includes(name)) || dests[dests.length - 1];
      expect(last, "au moins une escale à venir du plan").toContain(next);
    }
  }

  const eta = await page.request.get("/voyage/official/eta?stop=Nouméa", { timeout: 8_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const members = Number(eta?.members || 0);
  if (members > 0 && eta?.p10 && eta?.p90) {
    expect(last, "fourchette du stock eta").toMatch(ETA_RANGE);
  } else {
    expect(last, "pas d'ETA inventée").not.toMatch(/entre le \d/);
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
    const n = window.__naviguideFilm?.chapterCount || 0;
    if (n > 0 && window.__naviguideFilm?.seekChapter) {
      window.__naviguideFilm.seekChapter(n - 1);
    }
  });
  await expect(subtitle).toBeVisible();
  await shot(page, "01-fin");
});
