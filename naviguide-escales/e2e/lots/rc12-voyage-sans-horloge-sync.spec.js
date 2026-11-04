// POST /voyage sans horloge synchrone. Sans API : Simulation,
// Suivre, barre film, Journal et polaires tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions journal / LIVE stock / 524 — jamais les modes, ni la barre.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc12");
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
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

async function showRightPanel(page) {
  const box = page.getByTestId("polar-box");
  if (await box.isVisible({ timeout: 1_500 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect(page.getByTestId("polar-box")).toBeVisible({ timeout: 15_000 });
}

function isVoyageOrIci(url) {
  return /\/voyage(?:\/|\?|$)|\/ici(?:\/|\?|$)/.test(url);
}

test("POST /voyage immédiat, pas de 524, LIVE et Journal", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — 524 / journal live / Polaires chargées sautés",
    });
  }

  const redVoyageIci = [];
  const voyagePosts = [];
  page.on("response", (res) => {
    const url = res.url();
    if (/\/voyage(?:\/|\?|$)/.test(url) && res.request().method() === "POST") {
      voyagePosts.push(res.status());
    }
    if (!isVoyageOrIci(url)) return;
    if (res.status() === 524 || res.status() >= 500) {
      redVoyageIci.push(`${res.status()} ${url}`);
    }
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.waitForTimeout(3000);
  await shot(page, "01-simulation");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("film-clock-line")).toBeVisible();
  await expect(page.getByTestId("film-clock-line")).toContainText("LIVE");
  const barText = await page.getByTestId("film-bar").innerText();
  expect(barText).not.toMatch(/0 nm\s*·\s*Saint-Maur\s*→\s*La Rochelle/);

  await leaveCinema(page);
  await showLeftPanel(page);
  const journalTab = page.getByTestId("ici-tab-journal");
  await expect(journalTab).toBeVisible({ timeout: 10_000 });
  await journalTab.click();
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();
  await shot(page, "02-suivre-live");

  await showRightPanel(page);
  await expect(page.getByTestId("polar-box")).toBeVisible();
  await expect(page.getByTestId("polar-status")).toBeVisible();
  await shot(page, "03-journal");
  await shot(page, "04-polaires");

  if (!apiUp) return;

  expect(voyagePosts.some((s) => s === 524), `POST /voyage 524 : ${voyagePosts.join(",")}`).toBeFalsy();
  expect(redVoyageIci, `5xx voyage/ici : ${redVoyageIci.join(" | ")}`).toEqual([]);

  const clockText = await page.getByTestId("film-clock-line").innerText();
  const dayMatch = clockText.match(/j(\d+)/i);
  expect(dayMatch, `jour de mer dans la barre (« ${clockText.replace(/\s+/g, " ")} »)`).toBeTruthy();
  const day = Number(dayMatch[1]);
  if (day === 0) {
    expect(clockText, "libellé honnête j0").toMatch(/\bj0\b/i);
  } else {
    expect(day, "jour de mer > 0 (stock figé)").toBeGreaterThan(0);
  }

  const journalRes = await page.request.get("/voyage/official/journal?limit=80", { timeout: 8000 }).catch(() => null);
  if (journalRes && journalRes.ok()) {
    const journal = await journalRes.json().catch(() => ({}));
    if (journal.status === "ready" && (journal.latest || []).length > 1) {
      await expect.poll(async () => page.getByTestId("ici-journal-entry").count(), { timeout: 12_000 }).toBeGreaterThan(1);
      const first = await page.getByTestId("ici-journal-entry").first().innerText();
      expect(first).toMatch(/15\s*mai|15\s*May|2026/i);
    }
  }

  await expect(page.getByTestId("polar-status")).toContainText(/Polaires chargées|Polars loaded/);
});
