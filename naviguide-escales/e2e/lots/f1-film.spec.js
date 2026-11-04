// Chapitrage et cinématique menée par la voix.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-f1/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Film intégral, zoom fixe, sous-titre Saint-Maur", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  const official = await page.request.get("/voyage/official", { timeout: 4000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (apiUp) {
    await expect(page.getByTestId("film-duration")).toBeVisible({ timeout: 25_000 });
  } else {
    test.info().annotations.push({ type: "sans API", description: "pilules 2:30 / 3:00 seulement si Revoir peut partir" });
  }

  const start = page.getByTestId("replay-start");
  if (!(await start.isEnabled())) {
    test.info().annotations.push({ type: "sans film", description: "Revoir grisé — zoom / Saint-Maur non joués" });
    await shot(page, "01-depart");
    return;
  }
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await expect(subtitle).toContainText("Saint-Maur");
  await shot(page, "01-depart");

  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), { timeout: 10_000 });
  // Zoom fixe pendant une jambe. Le chapitre 1 (Saint-Maur → La Rochelle) est
  // court : on relance la fenêtre de 4 s si on a changé de chapitre.
  await page.waitForTimeout(1_500);
  let z0 = 0;
  let end = { z: 0, ch: -1 };
  let chapter = -1;
  for (let i = 0; i < 4; i++) {
    chapter = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);
    z0 = await page.evaluate(() => window.__naviguideScene.map.getZoom());
    await page.waitForTimeout(4_000);
    end = await page.evaluate(() => ({
      z: window.__naviguideScene.map.getZoom(),
      ch: window.__naviguideFilm?.chapterIdx ?? 0,
    }));
    if (end.ch === chapter) break;
  }
  expect(end.ch, "mesure à cheval sur deux chapitres").toBe(chapter);
  expect(Math.abs(end.z - z0), `zoom ${z0} → ${end.z}`).toBeLessThanOrEqual(0.01);

  await page.waitForFunction(() => {
    const el = document.querySelector("[data-testid='film-subtitle']");
    const text = el?.textContent || "";
    return text.length > 0 && (/Rochelle|Ajaccio|mer|Atlantique|Fort-de-France/i.test(text) || (window.__naviguideFilm?.chapterIdx ?? 0) >= 1);
  }, { timeout: 80_000 }).catch(() => {});
  await shot(page, "02-atlantique");

  // Sans durée cochée : plus de calage sur 2:30. La cible est le temps de parole
  // (filmSpeakSeconds, 16 car./s) et chaque chapitre servi reste un chapitre.
  const film = await page.evaluate(() => {
    const f = window.__naviguideFilm || {};
    const chapters = Array.isArray(f.chapters) ? f.chapters : [];
    const chars = chapters.reduce((s, c) => s + String(c?.text || "").length, 0);
    return {
      target: f.targetSeconds,
      budget: f.budgetSeconds,
      count: f.chapterCount || 0,
      n: chapters.length,
      chars,
    };
  });
  expect(film.budget, "aucune durée cochée").toBe(0);
  expect(film.n, "chapitres publiés").toBeGreaterThan(0);
  expect(film.count, "aucun chapitre fusionné").toBe(film.n);
  expect(film.target, "durée naturelle du texte").toBe(Math.max(1, Math.round(film.chars / 16)));
  if (apiUp) {
    const free = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    const servedN = Array.isArray(free?.chapters) ? free.chapters.length : 0;
    expect(servedN, "intégral servi").toBeGreaterThan(0);
    expect(film.count, "le lecteur garde chaque chapitre servi").toBe(servedN);
  }
  const stop = page.getByTestId("replay-stop");
  if (await stop.isVisible().catch(() => false)) await stop.click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await shot(page, "03-arrivee");
});
