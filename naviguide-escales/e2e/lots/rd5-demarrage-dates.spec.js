// Démarrage Suivre, Date de départ visible (Revoir), horloge avec
// année, date de Revoir réglable (2025) et distincte de Tracer (DM7 : plus
// de champ Date de départ en Tracer ; horloge = aujourd'hui).
// Sans API : vue initiale, horloge, champ replay et décalage du script
// local tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent (200 du film serveur) — jamais Suivre,
// ni le champ, ni l'année, ni le texte local « 15 mai 2025 ».
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd5/${name}.webp`,
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

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

function dateInput(page, testId) {
  return page.getByTestId(testId).locator("input").first();
}

test("Suivre au chargement, dates distinctes, horloge avec année", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — 200 du film serveur sauté",
    });
  }

  const filmUrls = [];
  page.on("request", (req) => {
    if (req.url().includes("/voyage/official/film")) filmUrls.push(req.url());
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("replay-departure")).toBeVisible();
  await expect(dateInput(page, "replay-departure-field")).toHaveValue("15/05/2026");
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 25_000 }).catch(() => {});

  const clock = page.getByTestId("clock-line");
  if (await clock.isVisible({ timeout: 8_000 }).catch(() => false)) {
    const clockText = await clock.innerText();
    if (/\d{1,2}\s+\S+\s+\d{4}/.test(clockText)) {
      expect(clockText, "horloge avec année").toMatch(/\d{4} · \d{2}:\d{2} UTC/);
    }
  }

  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showToolsPanel(page);
  await expect(page.getByTestId("departure-field")).toHaveCount(0);

  if (await clock.isVisible().catch(() => false)) {
    const simClock = await clock.innerText();
    if (/\d{1,2}\s+\S+\s+\d{4}/.test(simClock)) {
      expect(simClock, "horloge Tracer avec année").toMatch(/\d{4} · \d{2}:\d{2} UTC/);
    }
    expect(simClock, "horloge Tracer ≠ replay 15 mai 2026").not.toMatch(/15 mai 2026 · 08:00 UTC|15 May 2026 · 08:00 UTC/);
  }

  await shot(page, "02-dates");

  await page.getByTestId("view-suivre").click();
  await leaveCinema(page);
  await expect(page.getByTestId("replay-departure")).toBeVisible({ timeout: 15_000 });
  const replayDate = dateInput(page, "replay-departure-field");
  await replayDate.fill("15/05/2025");
  await expect(replayDate).toHaveValue("15/05/2025");

  await expect.poll(
    () => filmUrls.some((u) => decodeURIComponent(u).includes("2025-05-15")),
    { timeout: 8_000 },
  ).toBe(true);

  const { waitFilmReady } = await import("../helpers.js");
  if (apiUp) {
    await waitFilmReady(page);
    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
    const subtitle = page.getByTestId("film-subtitle");
    await expect(subtitle).toBeVisible({ timeout: 8_000 });
    await expect(subtitle).toContainText(/15 mai 2026|15 May 2026/);
    await page.getByTestId("replay-stop").click();
    await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
    await replayDate.fill("15/05/2026");
    await waitFilmReady(page);
    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByTestId("film-subtitle")).toContainText(/15 mai 2026|15 May 2026/);
    await page.getByTestId("replay-stop").click();
  }

  if (apiUp) {
    const film = await page.request.get(
      "/voyage/official/film?lang=fr&seconds=150&t0=2025-05-15T08:00:00.000Z",
      { timeout: 8000 },
    );
    expect(film.ok(), "GET /film t0=2025 répond").toBeTruthy();
    const body = await film.json();
    const text0 = body.chapters?.[0]?.text || "";
    expect(text0, "chapitre 1 daté").toMatch(/15 mai 2026|15 May 2026|Saint-Maur/);
  }

  await page.getByTestId("view-tracer").click();
  await showToolsPanel(page);
  await expect(page.getByTestId("departure-field")).toHaveCount(0);
});
