// FM1 — 2:30 / 3:00, estimée de la durée choisie, Stop propre.
// Sans API : Suivre et la barre restent ; les assertions de stock sont annotées.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema } from "../helpers.js";

function clockSeconds(text) {
  const m = String(text || "").match(/(\d+):(\d{2})/);
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

test("FM1 — variantes courtes, estimée, Stop", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(
    official && official.ok() && String(official.headers()["content-type"] || "").includes("json"),
  );
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions de stock sautées",
    });
  }

  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  const duration = page.getByTestId("film-duration");
  if (!(await duration.isVisible().catch(() => false))) {
    test.info().annotations.push({
      type: "pilules masquées",
      description: "Revoir pas prêt — 2:30 / 3:00 non affichés",
    });
    return;
  }

  const pill150 = duration.locator("[data-seconds='150']");
  const pill180 = duration.locator("[data-seconds='180']");
  await expect(pill150).toBeVisible();
  await expect(pill180).toBeVisible();

  let estimates = null;
  if (apiUp) {
    const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    estimates = film?.estimates && typeof film.estimates === "object" ? film.estimates : null;
    for (const sec of [150, 180]) {
      const row = estimates?.[String(sec)];
      if (row && Number(row.chars) > 0) {
        expect(Number(row.chars), `${sec} s dans film_char_budget`).toBeLessThanOrEqual(sec * 15);
      }
    }
  }

  const readClock = async () => clockSeconds(await page.getByTestId("film-duration-estimate").textContent().catch(() => ""));

  for (const sec of [150, 180]) {
    const pill = sec === 150 ? pill150 : pill180;
    if (await pill.getAttribute("data-variant-absent") === "1") {
      expect(await pill.getAttribute("title")).toBeTruthy();
      continue;
    }
    if (await pill.getAttribute("aria-pressed") !== "true") await pill.click();
    await expect(pill).toHaveAttribute("aria-pressed", "true");
    const row = estimates?.[String(sec)];
    const expected = Number(row?.estimatedSeconds);
    if (Number.isFinite(expected) && expected > 0 && expected <= sec * 1.1) {
      await expect.poll(readClock, { timeout: 8_000 }).toBeGreaterThanOrEqual(sec * 0.9);
      const shown = await readClock();
      expect(shown).toBeLessThanOrEqual(sec * 1.1);
    }
  }

  if (await pill180.getAttribute("data-variant-absent") !== "1" && await pill180.getAttribute("aria-pressed") === "true") {
    await pill180.click();
  }
  if (await pill150.getAttribute("data-variant-absent") !== "1" && await pill150.getAttribute("aria-pressed") === "true") {
    await pill150.click();
  }
  const integral = Number(estimates?.["0"]?.estimatedSeconds);
  if (Number.isFinite(integral) && integral > 0) {
    const shown = await readClock();
    if (shown != null) expect(Math.abs(shown - integral)).toBeLessThanOrEqual(1);
    if (integral === 335) {
      await expect(page.getByTestId("film-duration-estimate")).toContainText("5:35");
    }
  }

  const tilesBefore = await page.locator(".leaflet-tile-loaded").count();
  if (await start.isEnabled().catch(() => false)) {
    const listen = page.getByTestId("listen");
    if (await listen.isVisible().catch(() => false) && await listen.getAttribute("aria-pressed") === "true") {
      await listen.click();
    }
    if (await pill150.getAttribute("data-variant-absent") !== "1" && await pill150.getAttribute("aria-pressed") !== "true") {
      await pill150.click();
    }
    const pressed150 = await pill150.getAttribute("aria-pressed");
    await start.click();
    const stop = page.getByTestId("replay-stop");
    await expect(stop).toBeVisible({ timeout: 8_000 });
    if (pressed150 === "true") {
      const budget = await page.evaluate(() => window.__naviguideFilm?.targetSeconds ?? null);
      if (budget != null) {
        expect(budget).toBeGreaterThanOrEqual(150 * 0.9);
        expect(budget).toBeLessThanOrEqual(150 * 1.1);
      }
    }
    await stop.click();
  }

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();
  if (tilesBefore > 0) {
    await expect.poll(() => page.locator(".leaflet-tile-loaded").count(), { timeout: 8_000 }).toBeGreaterThan(0);
  }
});
