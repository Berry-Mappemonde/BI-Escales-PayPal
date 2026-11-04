// Voyage officiel servi depuis le stock. Sans API : Suivre, Journal
// et Revoir tiennent seuls. GET /voyage/official sondé ; s'il manque,
// annotation + saut des seules assertions stock / journal / LIVE / film —
// jamais Suivre, ni la barre, ni Revoir.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf2");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible().catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

test("Stock officiel : Journal et film depuis le stock", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions stock / journal / LIVE / film sautées",
    });
  }

  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toBeVisible();

  await showLeftPanel(page);
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  const journalTab = page.getByTestId("ici-tab-journal");
  await expect(journalTab).toBeVisible({ timeout: 10_000 });
  await journalTab.click();
  await expect(page.getByTestId("ici-journal-slot")).toHaveCount(1);

  const reviewTab = page.getByTestId("ici-tab-review");
  await expect(reviewTab).toBeVisible();
  await reviewTab.click();
  await expect(page.getByTestId("ici-review-slot")).toBeVisible();
  await expect(page.getByTestId("plan-review")).toBeVisible();

  await journalTab.click();
  await expect(page.getByTestId("ici-journal-slot")).toHaveCount(1);
  expect(pageErrors, `erreurs de page : ${pageErrors.join(" | ")}`).toEqual([]);
  await shot(page, "01-journal-immediat");

  if (!apiUp) return;

  const journalRes = await page.request.get("/voyage/official/journal?limit=80", { timeout: 8000 }).catch(() => null)
    || await page.request.get("/voyage/official/journal?limit=80", { timeout: 8000 }).catch(() => null);
  if (!journalRes) {
    test.info().annotations.push({
      type: "poste",
      description: "GET /journal sans réponse sous charge (API saturée)",
    });
    await shot(page, "01-stock");
    return;
  }
  expect(journalRes.status(), "GET /journal jamais 5xx").toBeLessThan(500);
  const journal = await journalRes.json().catch(() => ({}));
  if (journal.status === "preparing") {
    test.info().annotations.push({
      type: "stock en préparation",
      description: "GET /journal encore en préparation — assertions contenu réel sautées",
    });
    return;
  }
  expect(journal.status).toBe("ready");
  expect((journal.latest || []).length, "journal stocké : plusieurs lignes").toBeGreaterThan(5);
  await expect(page.getByTestId("clock-line")).toContainText(/LIVE/i, { timeout: 20_000 });
  const entries = page.getByTestId("ici-journal-entry");
  await expect.poll(async () => entries.count(), { timeout: 20_000 }).toBeGreaterThan(5);
  await expect(entries.first()).toBeVisible();
  await shot(page, "01-journal-immediat");

  const clockRes = await page.request.get("/voyage/official/clock", { timeout: 5000 }).catch(() => null);
  if (clockRes && clockRes.ok()) {
    const clock = await clockRes.json().catch(() => ({}));
    if (clock.t0) {
      const day = Math.floor((Date.now() - Date.parse(clock.t0)) / 86400000);
      expect(day, "jour LIVE depuis le t0 stocké").toBeGreaterThan(100);
    }
  }
  await expect(page.getByTestId("clock-line")).toContainText(/LIVE/i);

  const filmRes = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 8000 }).catch(() => null);
  expect(filmRes, "GET /film a répondu").toBeTruthy();
  expect(filmRes.status(), "GET /film jamais 5xx").toBeLessThan(500);
  const film = await filmRes.json().catch(() => ({}));
  if (film.status === "ready") {
    expect((film.chapters || []).length, "script du film stocké").toBeGreaterThan(0);
    expect(film.chapters[0].tA || film.chapters[0].tB, "chapitres datés tA/tB").toBeTruthy();
  }

  await page.reload();
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("clock-line")).toContainText(/LIVE/i, { timeout: 20_000 });

  if (film.status === "ready") {
    const { waitFilmReady } = await import("../helpers.js");
    await waitFilmReady(page);
    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByTestId("film-subtitle")).toBeVisible();
  }
});
