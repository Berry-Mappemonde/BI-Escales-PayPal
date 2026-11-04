// La phrase Halifax → Saint-Pierre dit les milles de cette jambe.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film. Barre, Suivre et Revoir restent exigés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmReady } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/fc2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const VOYAGE_MILES = /9[\s,\u00a0]?160|48\s+jours|48\s+days/;

test("Halifax vers Saint-Pierre dit les milles de la jambe", async ({ page }) => {
  test.setTimeout(300_000);
  await page.addInitScript(() => {
    try { delete window.speechSynthesis; } catch { /* ignore */ }
    Object.defineProperty(window, "speechSynthesis", { configurable: true, get: () => undefined });
    window.__fc2Films = [];
    const orig = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const raw = args[0] instanceof Request ? args[0].url : args[0];
      const url = String(raw || "");
      const res = await orig(...args);
      if (url.includes("/voyage/official/film") && !url.includes("style=written")) {
        const origJson = res.json.bind(res);
        res.json = async () => {
          const data = await origJson();
          try {
            const u = new URL(url, location.origin);
            const chapters = Array.isArray(data?.chapters) ? data.chapters : [];
            // Jambe nommée Halifax → Saint-Pierre, sinon (stock figé RF5 du 27 sept.,
            // antérieur au chapitre séparé) le chapitre qui raconte cet épisode.
            const said = (c, k) => `${String(c?.[k] || "")} ${String(c?.text || "")}`;
            const hop = chapters.find((c) => /Halifax/.test(String(c?.fromName || ""))
              && /Saint-Pierre/.test(String(c?.toName || "")))
              || chapters.find((c) => /Halifax/.test(said(c, "fromName"))
                && /Saint-Pierre/.test(said(c, "toName")));
            window.__fc2Films.push({
              seconds: u.searchParams.get("seconds"),
              n: chapters.length,
              chars: chapters.reduce((s, c) => s + String(c?.text || "").length, 0),
              estimatedSeconds: Number(data?.estimatedSeconds) || 0,
              status: data?.status || "",
              hop: String(hop?.text || ""),
              tA: String(hop?.tA || ""),
              tB: String(hop?.tB || ""),
            });
          } catch { /* ignore */ }
          return data;
        };
      }
      return res;
    };
  });

  const official = await page.request.get("/voyage/official", { timeout: 8_000 }).catch(() => null);
  const apiUp = Boolean(
    official && official.ok() && String(official.headers()["content-type"] || "").includes("json"),
  );

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
    await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-duration")).toHaveCount(0);
    return;
  }

  await waitFilmReady(page);
  const duration = page.getByTestId("film-duration");
  await expect(duration).toBeVisible();
  const pill = duration.locator("[data-seconds='150']");
  await expect(pill).toBeVisible();
  await expect(pill).toContainText("2:30");
  expect(await pill.getAttribute("data-variant-absent"), "la pilule 2:30 est jouable").not.toBe("1");

  const dropped = page.waitForFunction(() => {
    const b = document.querySelector("[data-testid='replay-start']");
    return Boolean(b && b.disabled);
  }, null, { timeout: 2_000 });
  if (await pill.getAttribute("aria-pressed") !== "true") await pill.click();
  await dropped;
  await expect(pill).toHaveAttribute("aria-pressed", "true");

  await page.waitForFunction(() => (window.__fc2Films || []).some((f) => f.seconds === "150" && f.n > 0), null, { timeout: 30_000 });
  await expect(start).toBeEnabled({ timeout: 15_000 });
  const served = await page.evaluate(() => {
    const films = window.__fc2Films || [];
    return {
      s150: films.filter((f) => f.seconds === "150").at(-1) || null,
      s0: films.filter((f) => f.seconds === "0").at(-1) || null,
    };
  });
  expect(served.s150?.status === "preparing", "le 2:30 servi n'est pas en préparation").toBe(false);
  const speak = served.s150.chars / 15;
  expect(speak, "lecture du texte 2:30").toBeGreaterThanOrEqual(110);
  expect(speak, "lecture du texte 2:30").toBeLessThanOrEqual(190);
  expect(served.s150.hop, "Halifax → Saint-Pierre est dans le texte 2:30").not.toBe("");
  // Les dates suivent l'horloge du stock servi (stock figé : arrivée à Saint-Pierre le 21 août),
  // pas une horloge de production d'un jour donné : on exige la fenêtre d'août, dans l'ordre.
  expect(served.s150.tA.startsWith("2026-08"), served.s150.tA).toBe(true);
  expect(served.s150.tB.startsWith("2026-08"), served.s150.tB).toBe(true);
  expect(Date.parse(served.s150.tB) > Date.parse(served.s150.tA), `${served.s150.tA} → ${served.s150.tB}`).toBe(true);
  expect(served.s150.hop).not.toMatch(VOYAGE_MILES);
  expect(served.s150.hop).toMatch(/milles|miles/);
  if ((served.s0?.chars || 0) / 15 > 190) {
    expect(served.s150.chars, "le 2:30 n'est pas le journal intégral").toBeLessThan(served.s0.chars);
  }

  const estimate = page.getByTestId("film-duration-estimate");
  await expect(estimate).toBeVisible();
  const estimateText = (await estimate.innerText()).trim();
  const shown = estimateText.match(/(\d+):(\d{2})/);
  expect(shown, estimateText).toBeTruthy();
  const shownSec = Number(shown[1]) * 60 + Number(shown[2]);
  expect(shownSec, "l'estimation affichée est celle du 2:30").toBeGreaterThanOrEqual(110);
  expect(shownSec, "l'estimation affichée est celle du 2:30").toBeLessThanOrEqual(190);
  test.info().annotations.push({ type: "estimee", description: estimateText });
  test.info().annotations.push({ type: "halifax-servi", description: served.s150.hop });
  await shot(page, "01-pilule");

  await page.evaluate(() => {
    window.__fc2Idx = [];
    const note = () => {
      const f = window.__naviguideFilm;
      if (!f) return;
      const i = f.chapterIdx;
      if (Number.isFinite(i) && window.__fc2Idx[window.__fc2Idx.length - 1] !== i) window.__fc2Idx.push(i);
    };
    const loop = () => {
      note();
      if (!window.__naviguideFilm?.ended) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });

  await start.click();
  await page.waitForFunction(() => (window.__naviguideFilm?.chapterCount || 0) > 0, null, { timeout: 15_000 });
  await page.evaluate(() => { window.__fc2T0 = performance.now(); });
  const opened = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const chapters = Array.isArray(f.chapters) ? f.chapters : [];
    const said = (c, k) => `${String(c?.[k] || "")} ${String(c?.text || "")}`;
    const hop = chapters.find((c) => /Halifax/.test(String(c?.fromName || ""))
      && /Saint-Pierre/.test(String(c?.toName || "")))
      || chapters.find((c) => /Halifax/.test(said(c, "fromName"))
        && /Saint-Pierre/.test(said(c, "toName")));
    return {
      count: f.chapterCount || 0,
      budget: f.budgetSeconds,
      n: chapters.length,
      chars: chapters.reduce((s, c) => s + String(c?.text || "").length, 0),
      hop: String(hop?.text || ""),
    };
  });
  expect(opened.count, "tous les chapitres chargés sont au lecteur").toBe(served.s150.n);
  expect(opened.n).toBe(served.s150.n);
  expect(opened.budget).toBe(150);
  expect(opened.chars).toBe(served.s150.chars);
  expect(opened.hop).toBe(served.s150.hop);
  expect(opened.hop).not.toMatch(VOYAGE_MILES);

  const matched = await page.waitForFunction(() => {
    const f = window.__naviguideFilm;
    const sub = (document.querySelector("[data-testid='film-subtitle']")?.textContent || "").replace(/\s+/g, " ").trim();
    const ch = f?.chapterText || "";
    if (/Halifax/.test(ch) && /Saint-Pierre/.test(ch) && /milles|miles/i.test(sub)) return sub;
    return null;
  }, null, { timeout: 180_000 });
  const subtitle = await matched.jsonValue();
  expect(subtitle).not.toMatch(VOYAGE_MILES);
  expect(subtitle).toMatch(/milles|miles/);
  test.info().annotations.push({ type: "sous-titre", description: subtitle });
  await shot(page, "02-halifax");

  await page.waitForFunction(() => window.__naviguideFilm?.ended === true, null, { timeout: 200_000 });
  const played = await page.evaluate(() => ({
    ended: Boolean(window.__naviguideFilm?.ended),
    count: window.__naviguideFilm?.chapterCount || 0,
    idx: window.__fc2Idx || [],
    wall: (performance.now() - window.__fc2T0) / 1000,
  }));
  expect(played.ended).toBe(true);
  expect(played.count).toBe(served.s150.n);
  expect(played.idx, `chapitres vus ${played.idx.join(",")}`).toEqual(
    Array.from({ length: served.s150.n }, (_, i) => i),
  );
  expect(played.wall, "le film se termine entre 1:50 et 3:10").toBeGreaterThanOrEqual(110);
  expect(played.wall, "le film se termine entre 1:50 et 3:10").toBeLessThanOrEqual(190);
  test.info().annotations.push({ type: "duree", description: `${played.wall.toFixed(1)} s` });

  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("replay-stop")).toHaveCount(0);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
});
