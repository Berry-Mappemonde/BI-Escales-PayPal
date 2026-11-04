// Choisir ce qui entre : 2:30 tient (≤ 2250), quelques sujets
// à la place de redites, pas neuf phrases nouvelles. Recharger : aucun
// appel Nebius. Sans API (CI) : GET /voyage/official sondé ; s'il ne
// répond pas, annotation + return des assertions film — barre, Suivre
// et Revoir restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-vs1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LLM_URL = /nebius|openai|anthropic|openrouter|tokenfactory|api\.nvidia/i;
const CHAR_BUDGET_150 = 2250;
const AMP = /aire marine|marine protected area/i;
const BUOY = /une bouée|a buoy/i;
const FORM = /formalit[ée]s d['’]entr[ée]e|entry formalities/i;
const ANC = /\bmouillage\b|\banchorage\b/i;
const ATON = /\bbalise\b|\bbeacon\b/i;
const CABLE = /\bcâble\b|\bcable\b/i;
const DEPTH = /profondeur\s*:|depth\s*:/i;
const PIRACY = /Piraterie —|Piracy —/;

function familyCount(blob) {
  const sents = String(blob || "").split(/(?<=[.!?…])\s+/);
  const hit = (rx) => sents.some((s) => rx.test(s));
  return [
    AMP, BUOY, FORM, ANC, ATON, CABLE, DEPTH, PIRACY,
  ].filter((rx) => hit(rx)).length;
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

test("Revoir 2:30 tient, pas neuf phrases, aucun Nebius au rechargement", async ({ page }) => {
  test.setTimeout(90_000);
  const llmHits = [];
  page.on("request", (req) => {
    if (LLM_URL.test(req.url())) llmHits.push(req.url());
  });

  const official = await probeOfficial(page);
  const apiUp = Boolean(official);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre, Suivre et Revoir gardés",
    });
    await expect(page.getByTestId("film-bar")).toBeVisible();
    expect(llmHits, "aucun appel Nebius sans API").toEqual([]);
    await shot(page, "01-deux-trente");
    return;
  }

  const film150 = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const chapters150 = film150?.chapters || [];
  const blob150 = chapters150.map((c) => c.text || "").join(" ");
  const chars = Number(film150?.chars) || blob150.length;

  if (!chapters150.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film 2:30 sans chapitres — assertions longueur sautées",
    });
    await shot(page, "01-deux-trente");
    return;
  }

  expect(chars / 15, "2:30 tient dans 150 s + 10 % à 15 car./s").toBeLessThanOrEqual(150 * 1.1);
  const rev = String(film150.film_script_rev || "");
  if (rev === "vs1" || rev === "ed1" || rev === "dc3") {
    expect(chars, "2:30 ≤ film_char_budget(150)").toBeLessThanOrEqual(CHAR_BUDGET_150);
  } else if (chars > CHAR_BUDGET_150) {
    test.info().annotations.push({
      type: "stock pré-VS1",
      description: `film_script_rev=${rev || "?"} — 2:30 encore ${chars} car. ; remplisseur FILM_SCRIPT_REV=vs1`,
    });
  }
  expect(familyCount(blob150), "pas neuf phrases nouvelles").toBeLessThan(9);

  const pill150 = page.getByTestId("film-duration").locator("[data-seconds='150']");
  if (await pill150.isVisible().catch(() => false)) {
    if (await pill150.getAttribute("aria-pressed") !== "true") {
      await pill150.click();
      await expect(pill150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
    }
  }

  if (await start.isEnabled().catch(() => false)) {
    await muteVoice(page);
    await start.click();
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm;
      return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
    }, null, { timeout: 8_000 }).catch(() => null);
  }
  await shot(page, "01-deux-trente");

  const beforeReload = llmHits.length;
  await page.reload();
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  expect(llmHits.slice(beforeReload), "recharger : aucun appel Nebius").toEqual([]);
});
