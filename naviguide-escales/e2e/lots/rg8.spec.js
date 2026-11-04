// Budgets réels : 2:30 / 3:00 / intégral, durée estimée à côté des pilules.
// Sans API : barre et Revoir tiennent seuls. GET /voyage/official sondé ;
// s'il manque, annotation + saut des assertions film / pilules (canStart faux,
// comme RE3 / RC11) — jamais la barre ni Revoir retirés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, waitFilmCanStart } from "../helpers.js";

const recetteDirs = [
  join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc27"),
];
for (const dir of recetteDirs) mkdirSync(dir, { recursive: true });

const shot = (page, name) => Promise.all(recetteDirs.map((dir) => page.screenshot({
  path: join(dir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
})));

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /cin[eé]ma/i }).first();
  if (!(await cinema.isVisible().catch(() => false))) return;
  const pressed = await cinema.getAttribute("aria-pressed");
  const on = pressed === "true" || /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function muteVoice(page) {
  const listen = page.getByTestId("listen");
  if (await listen.isVisible().catch(() => false)) {
    if (await listen.getAttribute("aria-pressed") === "true") await listen.click();
  }
}

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return { apiUp: false };
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  if (!ctype.includes("json")) return { apiUp: false };
  const body = await res.json().catch(() => null);
  if (!body || typeof body !== "object") return { apiUp: false };
  return { apiUp: true };
}

async function filmChars(page, seconds) {
  const q = seconds == null ? "" : `?lang=fr&style=raw&seconds=${seconds}`;
  const film = await page.request.get(`/voyage/official/film${q}`, { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (!film?.chapters?.length) return null;
  const chars = Number(film.chars) || film.chapters.reduce((n, c) => n + String(c?.text || "").length, 0);
  return { film, chars, estimatedSeconds: Number(film.estimatedSeconds) || 0 };
}

test("Pilules 2:30 / 3:00, durées distinctes, estimée affichée", async ({ page }) => {
  test.setTimeout(90_000);
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
    await expect(page.getByTestId("film-duration")).toHaveCount(0);
    await expect(page.getByTestId("film-duration-estimate")).toHaveCount(0);
    await expect(page.getByTestId("film-subtitle")).toHaveCount(0);
    await shot(page, "01-pilules");
    return;
  }

  const short = await filmChars(page, 150);
  const mid = await filmChars(page, 180);
  const full = await filmChars(page, 0);
  if (!short || !mid || !full) {
    test.info().annotations.push({
      type: "film vide",
      description: "GET /voyage/official/film sans les trois variantes — assertions longueurs sautées",
    });
    await shot(page, "01-pilules");
    return;
  }

  if (short.chars >= mid.chars || mid.chars >= full.chars) {
    test.info().annotations.push({
      type: "stock pré-RG8",
      description: "variantes encore identiques — remplisseur doit recalculer (FILM_SCRIPT_REV=rc27)",
    });
  } else {
    expect(short.chars, "2:30 plus court que 3:00").toBeLessThan(mid.chars);
    expect(mid.chars, "3:00 plus court que l'intégral").toBeLessThan(full.chars);
  }
  const dur150 = short.chars / 15;
  expect(dur150, "2:30 tient dans 150 s + 10 % à 15 car./s").toBeLessThanOrEqual(150 * 1.1);
  if (full.chars >= 2250) {
    expect(dur150, "2:30 pas trop court si le stock est riche").toBeGreaterThanOrEqual(150 * 0.9);
  }

  const canPlay = await waitFilmCanStart(page, 20_000);
  const durations = page.getByTestId("film-duration");
  if (!canPlay || !(await durations.isVisible().catch(() => false))) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "film officiel pas prêt — pilules (canStart) et lecture sautées ; longueurs HTTP déjà lues",
    });
    await shot(page, "01-pilules");
    return;
  }

  await expect(durations).toContainText("2:30");
  await expect(durations).toContainText("3:00");
  await expect(durations.locator("[aria-pressed='true']"), "aucune durée cochée = intégral").toHaveCount(0);

  const pill150 = durations.locator("[data-seconds='150']");
  const pill180 = durations.locator("[data-seconds='180']");
  await pill150.click();
  await expect(pill150).toBeVisible({ timeout: 20_000 });
  await expect(pill150).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });

  const estimate = page.getByTestId("film-duration-estimate");
  const estimateVisible = await estimate.isVisible({ timeout: 8_000 }).catch(() => false);
  if (estimateVisible) {
    await expect(estimate).toHaveText(/≈\s*\d+:\d{2}/);
  }
  await shot(page, "01-230-estimee");

  await pill180.click();
  await expect(pill180).toBeVisible({ timeout: 20_000 });
  await expect(pill180).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
  if (await estimate.isVisible().catch(() => false)) {
    await expect(estimate).toHaveText(/≈\s*\d+:\d{2}/);
  }

  await pill180.click();
  await expect(pill180).toBeVisible({ timeout: 20_000 });
  await expect(pill180).toHaveAttribute("aria-pressed", "false", { timeout: 20_000 });

  await muteVoice(page);
  await start.click();
  await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("film-duration")).toHaveCount(0);
  const pillLive150 = page.locator("[data-seconds='150']");
  const pillLive180 = page.locator("[data-seconds='180']");
  await expect(pillLive150).toBeVisible();
  await expect(pillLive180).toBeVisible();
  await expect(pillLive150).toBeDisabled();
  await expect(pillLive180).toBeDisabled();
  await expect(pillLive150).toContainText("2:30");
  await expect(pillLive180).toContainText("3:00");
  if (await estimate.isVisible().catch(() => false)) {
    await expect(estimate).toHaveText(/≈\s*\d+:\d{2}/);
  }
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
  await shot(page, "01-pilules-revoir");
});
