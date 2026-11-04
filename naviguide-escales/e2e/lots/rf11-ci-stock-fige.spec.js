// Stock figé en CI. Sans API : barre, Suivre et Revoir tiennent
// seuls. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions journal / horloge / film — jamais Suivre, ni Revoir.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf11");
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

test("Journal, horloge et film servis depuis le stock figé", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions stock / journal / horloge / film sautées",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible();

  if (!apiUp) {
    await shot(page, "02-suivre-sans-api");
    return;
  }

  const journalRes = await page.request.get("/voyage/official/journal?limit=80", { timeout: 20_000 });
  expect(journalRes.status(), "GET /journal jamais 5xx").toBeLessThan(500);
  const journal = await journalRes.json();
  expect(journal.status, "journal figé prêt — plus un saut").toBe("ready");
  expect((journal.latest || []).length, "journal figé : plusieurs lignes").toBeGreaterThan(5);
  expect(journal.dataDate, "dataDate du stock servi").toBeTruthy();
  expect(journal.storedAt, "storedAt du stock servi").toBeTruthy();

  const clockRes = await page.request.get("/voyage/official/clock", { timeout: 20_000 });
  expect(clockRes.status()).toBe(200);
  const clock = await clockRes.json();
  expect(clock.t0, "horloge figée").toBeTruthy();
  expect(clock.status || "ready").not.toBe("preparing");

  const filmRes = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 20_000 });
  expect(filmRes.status()).toBeLessThan(500);
  const film = await filmRes.json();
  expect(film.status, "film figé prêt").toBe("ready");
  expect((film.chapters || []).length, "script du film stocké").toBeGreaterThan(0);

  await expect(page.getByTestId("clock-line")).toContainText(/LIVE/i, { timeout: 20_000 });
  await shot(page, "02-suivre-stock");
});
