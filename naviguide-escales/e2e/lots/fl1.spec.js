// 2:30 joue chaque chapitre du texte jusqu'à ended=true.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation
// + return des assertions film. Barre, Suivre et Revoir restent exigés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, waitFilmReady } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/fl1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Revoir 2:30 joue chaque chapitre jusqu'au bout", async ({ page }) => {
  test.setTimeout(300_000);
  await page.addInitScript(() => {
    window.__fl1FilmUrls = [];
    const orig = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const raw = args[0] instanceof Request ? args[0].url : args[0];
      const url = String(raw || "");
      if (url.includes("/voyage/official/film")) window.__fl1FilmUrls.push(url);
      const res = await orig(...args);
      if (url.includes("/voyage/official/film") && url.includes("seconds=150") && !url.includes("style=written")) {
        const origJson = res.json.bind(res);
        res.json = async () => {
          const data = await origJson();
          const chapters = Array.isArray(data?.chapters) ? data.chapters : [];
          const last = String(chapters[chapters.length - 1]?.text || "");
          const parts = last.split(/(?<=[.!?…])\s+/).filter(Boolean);
          const tail = parts[parts.length - 1] || "";
          window.__fl1Served150 = {
            n: chapters.length,
            chars: chapters.reduce((s, c) => s + String(c?.text || "").length, 0),
            estimatedSeconds: Number(data?.estimatedSeconds) || 0,
            status: data?.status || "",
            opening: String(chapters[0]?.text || "").slice(0, 80),
            closing: /aujourd|today/i.test(tail) ? tail : last,
          };
          return data;
        };
      }
      return res;
    };
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });

  const official = await page.request.get("/voyage/official", { timeout: 8_000 }).catch(() => null);
  const apiUp = Boolean(
    official && official.ok() && String(official.headers()["content-type"] || "").includes("json"),
  );
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions film sautées ; barre, Suivre et Revoir gardés",
    });
    await expect(page.getByTestId("film-bar")).toBeVisible();
    await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
    await shot(page, "01-sans-api");
    return;
  }

  await waitFilmReady(page);
  const duration = page.getByTestId("film-duration");
  await expect(duration).toBeVisible();
  const pill150 = duration.locator("[data-seconds='150']");
  await expect(pill150).toBeVisible();
  await expect(pill150).toContainText("2:30");

  expect(await pill150.getAttribute("data-variant-absent"), "la pilule 2:30 est jouable").not.toBe("1");

  if (await pill150.getAttribute("aria-pressed") !== "true") await pill150.click();
  await expect(pill150).toHaveAttribute("aria-pressed", "true");
  try {
    await page.waitForFunction(() => (window.__fl1Served150?.n || 0) > 0, null, { timeout: 90_000 });
  } catch (err) {
    const urls = await page.evaluate(() => window.__fl1FilmUrls || []);
    throw new Error(`${err.message} filmUrls=${JSON.stringify(urls)}`);
  }
  const served = await page.evaluate(() => window.__fl1Served150);
  expect(served.n, "le GET 2:30 a des chapitres").toBeGreaterThan(0);
  expect(served.status === "preparing", "le 2:30 servi n'est pas en préparation").toBe(false);

  if (served.estimatedSeconds === 162) {
    await expect(page.getByTestId("film-duration-estimate")).toHaveText("≈ 2:42");
  }

  await page.evaluate(() => {
    window.__fl1Idx = [];
    const note = () => {
      const f = window.__naviguideFilm;
      if (!f) return;
      const i = f.chapterIdx;
      if (Number.isFinite(i) && window.__fl1Idx[window.__fl1Idx.length - 1] !== i) window.__fl1Idx.push(i);
    };
    const loop = () => {
      note();
      if (!window.__naviguideFilm?.ended) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });

  await start.click();
  await page.waitForFunction(() => (window.__naviguideFilm?.chapterCount || 0) > 0, null, { timeout: 15_000 });
  const opened = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const chapters = Array.isArray(f.chapters) ? f.chapters : [];
    return {
      count: f.chapterCount || 0,
      budget: f.budgetSeconds,
      target: f.targetSeconds,
      chars: chapters.reduce((s, c) => s + String(c?.text || "").length, 0),
      n: chapters.length,
    };
  });
  expect(opened.count, "le lecteur ne fusionne pas les chapitres servis").toBe(served.n);
  expect(opened.n).toBe(served.n);
  if (served.n === 15) {
    expect(opened.count).toBe(15);
    expect(opened.n).toBe(15);
  }
  expect(opened.budget).toBe(150);
  expect(opened.target).toBe(150);
  expect(opened.chars).toBe(served.chars);

  await expect(page.getByTestId("replay-stop")).toBeVisible();
  if (served.opening.includes("Saint-Maur")) {
    await expect(page.getByTestId("film-subtitle")).toContainText("Saint-Maur");
    await expect(page.getByTestId("film-subtitle")).toContainText("La Rochelle");
  }
  await shot(page, "01-depart");

  await page.waitForFunction(() => window.__naviguideFilm?.ended === true, null, { timeout: 240_000 });
  const played = await page.evaluate(() => ({
    ended: Boolean(window.__naviguideFilm?.ended),
    count: window.__naviguideFilm?.chapterCount || 0,
    idx: window.__fl1Idx || [],
    // Publié dans le même tick que la fin (sans la latence du rendu React).
    filmSubtitle: String(window.__naviguideFilm?.subtitle || ""),
  }));
  expect(played.ended).toBe(true);
  expect(played.count).toBe(served.n);
  if (served.n === 15) expect(played.count).toBe(15);
  if (served.closing.includes("Dzaoudzi")) {
    // Le tick de fin publie la phrase de clôture (pas la 1re phrase du dernier chapitre).
    expect(played.filmSubtitle, "sous-titre publié au tick de fin").toContain("Dzaoudzi");
    // Le DOM suit au rendu React suivant (runner CI chargé) : on attend, sans relâcher l'assertion.
    await expect(page.getByTestId("film-subtitle")).toContainText("Dzaoudzi", { timeout: 5_000 });
  }
  expect(played.idx, `chapitres vus ${played.idx.join(",")}`).toEqual(
    Array.from({ length: served.n }, (_, i) => i),
  );

  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("replay-stop")).toHaveCount(0);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await shot(page, "02-fin");
});
