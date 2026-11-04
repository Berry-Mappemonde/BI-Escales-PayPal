// Film public : hors API, Revoir reste grisé. Avec API, le GET 150 s
// a des chapitres et le récit part. GET /voyage/official est sondé ;
// s'il ne répond pas, les assertions qui en dépendent sont sautées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ft1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("film 150 s : chapitres si l'API répond, Revoir grisé sinon", async ({ page }) => {
  test.setTimeout(60_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions du film sautées",
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
    await expect(page.getByTestId("film-duration")).toHaveCount(0);
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-revoir-grise");
    return;
  }

  const filmRes = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 15_000 });
  expect(filmRes.ok()).toBeTruthy();
  const film = await filmRes.json();
  const chapters = Array.isArray(film.chapters) ? film.chapters : [];
  if (chapters.length === 0) {
    test.info().annotations.push({
      type: "film",
      description: "réponse en préparation — chapitres non exigés",
    });
    expect(film.status).toBe("preparing");
    await expect(start).toBeDisabled();
    await shot(page, "01-revoir-grise");
    return;
  }

  expect(film.status).toBe("ready");
  expect(chapters.length).toBeGreaterThan(0);
  expect(String(chapters[0].text || "")).toMatch(/Saint-Maur/);
  await expect(start).toBeEnabled({ timeout: 15_000 });
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  await expect(subtitle).toContainText("Saint-Maur");
  await shot(page, "01-revoir-depart");
  const stop = page.getByTestId("replay-stop");
  if (await stop.isVisible().catch(() => false)) await stop.click();
});
