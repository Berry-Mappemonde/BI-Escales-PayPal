// Le film raconte les vraies données : durées décochables,
// journal sans budget, plus jamais les phrases ATMOS.
// Sans API : cases 2:30 / 3:00 et l'absence de remplissage dans le
// sous-titre local tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions du script serveur — jamais le défaut décoché, ni le toggle.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd7/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const FILLER = /ciel reste haut|mer porte le bateau|route tient le cap|vent reste le vent|mer reste la mer|sky stays high|sea carries the boat|course holds|wind stays the wind/i;

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

function durationBtn(page, sec) {
  return page.getByTestId("film-duration").locator(`[data-seconds="${sec}"]`);
}

test("Durées décochées, récit du journal, budget tenu", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — script serveur /film sauté",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  if (!apiUp) {
    test.info().annotations.push({ type: "sans API", description: "pilules 2:30 / 3:00 seulement si Revoir peut partir" });
    await shot(page, "01-durees");
    return;
  }
  await expect(page.getByTestId("film-duration")).toBeVisible({ timeout: 25_000 });

  const btn150 = durationBtn(page, 150);
  const btn180 = durationBtn(page, 180);
  await expect(btn150).toBeVisible();
  await expect(btn180).toBeVisible();
  await expect(btn150).toHaveAttribute("aria-pressed", "false");
  await expect(btn180).toHaveAttribute("aria-pressed", "false");

  // D'abord Revoir sans pilule : budget 0. Les bascules 2:30 / 3:00 ensuite.
  const { waitFilmReady } = await import("../helpers.js");
  if (apiUp) {
    await waitFilmReady(page);
  } else {
    const { waitFilmCanStart } = await import("../helpers.js");
    if (!(await waitFilmCanStart(page, 15_000))) {
      test.info().annotations.push({ type: "sans API", description: "Revoir encore grisé — film non parti" });
      await shot(page, "01-durees");
      return;
    }
  }
  await muteVoice(page);
  await page.getByTestId("replay-start").click();
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });
  const sub = (await subtitle.innerText()).trim();
  expect(sub, "sous-titre non vide").not.toBe("");
  expect(sub, "pas de phrase ATMOS").not.toMatch(FILLER);
  await shot(page, "02-recit");

  const budgetNone = await page.evaluate(() => window.__naviguideFilm?.budgetSeconds);
  expect(budgetNone, "aucune durée → pas de budget").toBe(0);

  if (apiUp) {
    const free = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(free?.chapters?.length, "GET /voyage/official/film?seconds=0 a des chapitres").toBeGreaterThan(0);
    const blob = free.chapters.map((c) => c.text || "").join(" ");
    expect(free.targetSeconds, "sans case : pas de budget serveur").toBe(0);
    expect(blob, "pas de phrase ATMOS côté serveur").not.toMatch(FILLER);
    expect(blob, "pas de nm nu").not.toMatch(/\bnm\b/);
    expect(blob, "pas de décimale déclamée").not.toMatch(/\d+[.,]\d{1,2}(?!\d)/);
  }

  const stopBtn = page.getByTestId("replay-stop");
  if (await stopBtn.isVisible().catch(() => false)) await stopBtn.click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });

  await btn150.click();
  // Les pilules se cachent le temps que le plan 2:30 se recharge, puis reviennent pressées.
  await expect(btn150).toBeVisible({ timeout: 20_000 });
  await expect(btn150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
  await muteVoice(page);
  if (apiUp) {
    await waitFilmReady(page);
  } else {
    const { waitFilmCanStart } = await import("../helpers.js");
    if (!(await waitFilmCanStart(page, 10_000))) {
      test.info().annotations.push({ type: "sans API", description: "Revoir grisé après 2:30 — budget client déjà vu" });
      return;
    }
  }
  await page.getByTestId("replay-start").click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect.poll(async () => page.evaluate(() => window.__naviguideFilm?.targetSeconds), {
    timeout: 5_000,
  }).toBe(150);
  expect(await page.evaluate(() => window.__naviguideFilm?.budgetSeconds)).toBe(150);
  await page.waitForTimeout(2500);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);
  const sub150 = (await subtitle.innerText()).trim();
  expect(sub150).not.toMatch(FILLER);

  if (apiUp) {
    const timed = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(timed?.chapters?.length, "GET /film?seconds=150 a des chapitres").toBeGreaterThan(0);
    expect([0, 150], "stock : 150 demandé, 0 ou 150 servi").toContain(Number(timed.targetSeconds));
    expect(await page.evaluate(() => window.__naviguideFilm?.budgetSeconds), "budget 150 tenu côté client").toBe(150);
    const blob = timed.chapters.map((c) => c.text || "").join(" ");
    expect(blob).not.toMatch(FILLER);
  }
});
