// Client robuste : sans voix, horloge murale ; sous-titre = une phrase.
// Sans API : barre et Revoir tiennent seuls. GET /voyage/official sondé ;
// s'il manque, annotation + saut des assertions film — jamais la barre ni Revoir.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmCanStart } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc23");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

function chapterSentences(text) {
  return String(text || "").split(/(?<=[.!?…])\s+/).map((s) => s.trim()).filter(Boolean);
}

function expectSubtitleIsPhrase(subtitle, chapterText, label) {
  const sub = String(subtitle || "").trim();
  const chap = String(chapterText || "").trim();
  if (!sub || !chap) return;
  const parts = chapterSentences(chap);
  if (parts.length <= 1) {
    expect(sub.length, label).toBeLessThanOrEqual(chap.length);
  } else {
    expect(sub.length, `${label} — une phrase, pas le chapitre`).toBeLessThan(chap.length);
  }
  expect(chap.includes(sub) || parts.some((p) => p === sub || p.startsWith(sub)), label).toBeTruthy();
}

test("Sans voix le film roule, sous-titre = phrase", async ({ page }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => {
    try { delete window.speechSynthesis; } catch { /* ignore */ }
    Object.defineProperty(window, "speechSynthesis", { configurable: true, get: () => undefined });
  });

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
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-sous-titre-phrase");
    return;
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  if (!canPlay) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — lecture sautée ; barre et Revoir gardés",
    });
    await shot(page, "01-sous-titre-phrase");
    return;
  }

  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });

  const first = (await subtitle.innerText()).trim();
  expect(first.length).toBeGreaterThan(0);
  const atStart = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const i = Number.isFinite(Number(f.chapterIdx)) ? Number(f.chapterIdx) : 0;
    const fromList = String(f.chapters?.[i]?.text || f.chapters?.[0]?.text || "");
    return {
      chapterText: String(f.chapterText || fromList),
      subtitle: String(f.subtitle || ""),
      charIdx: Number(f.charIdx) || 0,
    };
  });
  const startChapter = atStart.chapterText;
  expect(startChapter.length, "chapitre publié").toBeGreaterThan(0);
  expectSubtitleIsPhrase(first, startChapter, "DOM au départ");
  if (atStart.subtitle) expectSubtitleIsPhrase(atStart.subtitle, startChapter, "__naviguideFilm.subtitle au départ");
  const startParts = chapterSentences(startChapter);
  if (startParts.length > 1) {
    expect(first.includes(startParts[1]), "la 2e phrase n'est pas dans le sous-titre au départ").toBeFalsy();
  }
  if (atStart.charIdx === 0) {
    await expect(page.getByTestId("film-subtitle-place")).toHaveCount(0);
  }
  await page.waitForTimeout(800);
  await shot(page, "01-sous-titre-phrase");
  const place = page.getByTestId("film-subtitle-place");
  const placeOn = await place.waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false);
  if (placeOn) {
    await shot(page, "02-lieu-en-avant");
  }
  await page.evaluate((prev) => { window.__rg9FirstSubtitle = prev; }, first);

  await page.waitForTimeout(2500);
  const mid = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    return {
      ended: Boolean(f.ended),
      elapsed: Number(f.elapsed) || 0,
      chapterText: String(f.chapterText || ""),
      subtitle: String(f.subtitle || ""),
    };
  });
  expect(mid.ended, "ne doit pas finir à ~2,5 s").toBe(false);
  expect(mid.elapsed).toBeGreaterThan(1.5);
  expectSubtitleIsPhrase(mid.subtitle || (await subtitle.innerText()).trim(), mid.chapterText, "à ~2,5 s");

  await page.waitForFunction(() => {
    const el = document.querySelector("[data-testid='film-subtitle']");
    const now = (el?.textContent || "").trim();
    return Boolean(now && now !== window.__rg9FirstSubtitle);
  }, null, { timeout: 30_000 });
  const next = (await subtitle.innerText()).trim();
  expect(next).not.toEqual(first);
  const laterChapter = await page.evaluate(() => String(window.__naviguideFilm?.chapterText || ""));
  expectSubtitleIsPhrase(next, laterChapter || startChapter, "phrase suivante");

  const later = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    return { ended: Boolean(f.ended), elapsed: Number(f.elapsed) || 0 };
  });
  expect(later.ended, "sans voix, ended seulement à la fin").toBe(false);
  expect(later.elapsed).toBeGreaterThan(mid.elapsed - 0.2);

  await shot(page, "03-sous-titre-phrase-suivante");
});
