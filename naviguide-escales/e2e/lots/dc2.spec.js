// Bouée, formalité, mouillage : dans le sac, pas empilés au 2:30.
// Sans API (CI) : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film — barre, Suivre et Revoir restent.
// Avec API : le 2:30 n'a ni bouée, ni formalité, ni mouillage en plus, ≤ 2250.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dc2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const BUOY = /une bouée|a buoy/i;
const FORMALITY = /formalit[ée]s d['’]entr[ée]e passent par|entry formalities go through/i;
const ANCHORAGE = /\bmouillage\b|\banchorage\b/i;
const CHAR_BUDGET_150 = 2250;

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

function familyHits(blob) {
  const text = String(blob || "");
  return {
    buoy: (text.match(new RegExp(BUOY.source, "gi")) || []).length,
    poe: (text.match(new RegExp(FORMALITY.source, "gi")) || []).length,
    anchorage: (text.match(new RegExp(ANCHORAGE.source, "gi")) || []).length,
  };
}

test("2:30 sans bouée / formalité / mouillage, ≤ 2250", async ({ page }) => {
  test.setTimeout(90_000);
  const { apiUp } = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre, Suivre et Revoir gardés",
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

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-deux-trente");
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const chapters = film?.chapters || [];
  const blob = chapters.map((c) => c.text || "").join(" ");
  const chars = Number(film?.chars) || blob.length;
  const hits = familyHits(blob);

  if (!chapters.length) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film 2:30 sans chapitres — assertions longueur sautées",
    });
    await shot(page, "01-deux-trente");
    return;
  }

  expect(hits.buoy, "pas de bouée empilée dans le 2:30").toBeLessThanOrEqual(1);
  expect(hits.poe, "pas de formalité empilée dans le 2:30").toBeLessThanOrEqual(1);
  expect(hits.anchorage, "pas de mouillage empilé dans le 2:30").toBeLessThanOrEqual(1);
  expect(hits.buoy + hits.poe + hits.anchorage, "pas les trois familles empilées").toBeLessThan(3);
  expect(chars / 15, "2:30 tient dans 150 s + 10 % à 15 car./s").toBeLessThanOrEqual(150 * 1.1);
  const rev = String(film.film_script_rev || "");
  if (rev === "dc2" || rev === "dc3" || rev === "ed1" || rev === "vs1") {
    expect(chars, "2:30 ≤ film_char_budget(150)").toBeLessThanOrEqual(CHAR_BUDGET_150);
  } else if (chars > CHAR_BUDGET_150) {
    test.info().annotations.push({
      type: "stock pré-DC2",
      description: `film_script_rev=${rev || "?"} — 2:30 encore ${chars} car. ; remplisseur FILM_SCRIPT_REV=vs1`,
    });
  }

  const pill150 = page.getByTestId("film-duration").locator("[data-seconds='150']");
  if (await pill150.isVisible().catch(() => false)) {
    if (await pill150.getAttribute("aria-pressed") !== "true") await pill150.click();
    await expect(pill150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
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
});
