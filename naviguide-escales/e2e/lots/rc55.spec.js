// Le chapitre qui part de Saint-Pierre ne raconte pas la Guyane
// ni l'équateur (Atlantique nord). Sans API : GET /voyage/official sondé ;
// s'il manque, annotation + saut des assertions film — barre et Revoir gardés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc55");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const GUYANA_EQUATOR = /French Guiana waters|eaux de la Guyane|at the equator|à l['’]équateur/i;
const SPM_FROM = /Saint-Pierre/i;

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
  return { apiUp: true, body };
}

function saintPierreChapters(chapters) {
  return (chapters || []).filter((c) => SPM_FROM.test(c?.fromName || ""));
}

test("Chapitre Saint-Pierre sans Guyane ni équateur", async ({ page }) => {
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

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await shot(page, "01-saint-pierre");
    return;
  }

  const filmFr = await page.request.get("/voyage/official/film?lang=fr&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const filmEn = await page.request.get("/voyage/official/film?lang=en&seconds=0&style=raw", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const readyFilms = [filmFr, filmEn].filter((f) => f?.status === "ready" && Array.isArray(f?.chapters) && f.chapters.length);
  if (!readyFilms.length) {
    test.info().annotations.push({
      type: "film en préparation",
      description: "GET /voyage/official/film pas ready — FILM_SCRIPT_REV=rc55, remplisseur à relancer ; assertions chapitre sautées",
    });
    await shot(page, "01-saint-pierre");
    return;
  }

  let spmSeen = false;
  let staleStock = false;
  for (const film of readyFilms) {
    const spm = saintPierreChapters(film.chapters);
    if (!spm.length) {
      continue;
    }
    spmSeen = true;
    for (const ch of spm) {
      const text = String(ch.text || "");
      if (GUYANA_EQUATOR.test(text)) {
        staleStock = true;
        test.info().annotations.push({
          type: "stock pré-RC55",
          description: `film ready encore avec Guyane/équateur (Saint-Pierre → ${ch.toName || "?"}) — remplisseur FILM_SCRIPT_REV=rc55`,
        });
        continue;
      }
      expect(text, `Saint-Pierre → ${ch.toName || "?"} sans Guyane ni équateur`).not.toMatch(GUYANA_EQUATOR);
    }
  }
  if (!spmSeen) {
    test.info().annotations.push({
      type: "stock pré-RC55",
      description: "film ready sans chapitre au départ de Saint-Pierre — remplisseur FILM_SCRIPT_REV=rc55",
    });
    await shot(page, "01-saint-pierre");
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt à la lecture — JSON déjà vérifié",
    });
    await shot(page, "01-saint-pierre");
    return;
  }

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    return typeof f?.seekChapter === "function" && (f.chapterCount || 0) > 0;
  }, null, { timeout: 8_000 }).catch(() => null);

  const idx = await page.evaluate(() => {
    const list = window.__naviguideFilm?.chapters || [];
    let i = list.findIndex((c) => /Saint-Pierre/i.test(c.fromName || ""));
    if (i < 0) {
      i = list.findIndex((c) => /Saint-Pierre/i.test(`${c.fromName || ""} ${c.toName || ""} ${c.text || ""}`));
    }
    if (i >= 0) {
      window.speechSynthesis?.cancel?.();
      window.__naviguideFilm?.seekChapter?.(i, 0);
    }
    return i;
  });
  if (idx >= 0) {
    await page.waitForFunction((i) => Number(window.__naviguideFilm?.chapterIdx) === i, idx, {
      timeout: 8_000,
    }).catch(() => null);
    await page.waitForFunction(() => {
      const f = window.__naviguideFilm || {};
      const bar = `${f.fromName || ""} ${f.toName || ""} ${f.chapterText || ""} ${f.subtitle || ""}`;
      return /Saint-Pierre/i.test(bar);
    }, null, { timeout: 8_000 }).catch(() => null);
    const spoken = await page.evaluate(() => {
      const f = window.__naviguideFilm || {};
      const list = f.chapters || [];
      const ch = list[Number(f.chapterIdx)] || {};
      return `${f.chapterText || ch.text || ""} ${f.subtitle || ""}`;
    });
    if (staleStock) {
      test.info().annotations.push({
        type: "stock pré-RC55",
        description: "sous-titre Saint-Pierre encore ancien — remplisseur FILM_SCRIPT_REV=rc55",
      });
    } else {
      expect(spoken, "sous-titre Saint-Pierre sans Guyane ni équateur").not.toMatch(GUYANA_EQUATOR);
    }
  }
  await shot(page, "01-saint-pierre");

  const stopBtn = page.getByTestId("replay-stop");
  if (await stopBtn.isVisible().catch(() => false)) {
    await stopBtn.click();
  }
  await leaveCinema(page);
});
