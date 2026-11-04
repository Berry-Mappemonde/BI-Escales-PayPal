// Fabrication du film : l'écran Suivre ne change pas.
// GET /voyage/official est sondé ; s'il ne répond pas, les assertions
// qui en dépendent sont sautées. Celles de la barre restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ft2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("barre du film toujours là ; chapitres seulement si l'API répond", async ({ page }) => {
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
  await expect(page.getByTestId("view-suivre")).toContainText("Suivre");

  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await expect(start).toContainText("Revoir");

  if (!apiUp) {
    await expect(start).toBeDisabled();
    await expect(page.getByTestId("film-duration")).toHaveCount(0);
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-barre-film");
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
    await expect(page.getByTestId("film-duration")).toHaveCount(0);
    await shot(page, "01-barre-film");
    return;
  }

  expect(film.status).toBe("ready");
  expect(chapters.length).toBeGreaterThan(0);
  const opening = String(chapters[0].text || "").trim();
  expect(opening.length).toBeGreaterThan(0);
  await expect(start).toBeEnabled({ timeout: 15_000 });
  await expect(page.getByTestId("film-duration")).toBeVisible();
  await expect(page.getByRole("button", { name: "2:30" })).toBeVisible();
  await expect(page.getByRole("button", { name: "3:00" })).toBeVisible();
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
  await start.click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const snippet = opening.slice(0, 24);
  await expect(subtitle).toContainText(snippet);
  await shot(page, "01-barre-film");
  const stop = page.getByTestId("replay-stop");
  if (await stop.isVisible().catch(() => false)) await stop.click();
});
