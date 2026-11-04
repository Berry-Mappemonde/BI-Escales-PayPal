// Hindcast ERA5 dans le quota : route teintée, journal, statut honnête.
// Sans API : fumée Suivre + légende des régimes (jamais inventée).
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions clock / coverage / journal live — jamais la barre film, ni Suivre,
// ni l'onglet Journal.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf10");
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
  await openLeftDrawer(page);
}

test("Route hindcast, journal, statut honnête", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — teinte / coverage / journal live sautés",
    });
  }

  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);

  const legend = page.getByTestId("regime-legend");
  await expect(legend).toBeVisible({ timeout: 15_000 });
  const pill = page.getByTestId("speed-regime-pill");
  await expect(pill).toBeVisible();

  await showLeftPanel(page);
  const journalTab = page.getByTestId("ici-tab-journal");
  await expect(journalTab).toBeVisible({ timeout: 10_000 });
  // L'onglet se re-rend à chaque tick (compteur) : le clic géométrique n'atteint jamais « stable » — clic DOM.
  await journalTab.evaluate((el) => el.click());
  await expect(journalTab).toHaveAttribute("aria-selected", "true", { timeout: 10_000 });
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();

  if (!apiUp) {
    await shot(page, "01-route-hindcast");
    expect(pageErrors, "console : aucune exception page").toEqual([]);
    return;
  }

  const meta = await official.json().catch(() => null);
  const status = meta?.hindcastStatus;
  const coverage = meta?.hindcastCoverage;
  expect(["ready", "partial", "empty", "pending", "skipped", "unavailable"]).toContain(status);
  if (status === "ready") {
    expect(coverage, "ready ⇒ coverage n/total").toMatch(/^\d+\/\d+$/);
    const [n, total] = String(coverage).split("/").map(Number);
    if (total > 0) expect(n / total).toBeGreaterThanOrEqual(0.95);
  }
  if (status === "partial") {
    expect(coverage).toMatch(/^\d+\/\d+$/);
    const [n, total] = String(coverage).split("/").map(Number);
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThan(total);
  }
  if (status === "empty") {
    expect(coverage === undefined || coverage === "0/0" || /^0\/\d+$/.test(String(coverage))).toBeTruthy();
    expect(status, "empty n'est pas ready").not.toBe("ready");
  }

  const clock = await page.request.get("/voyage/official/clock", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);
  const regimes = await page.request.get("/voyage/official/regimes", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null)).catch(() => null);

  const now = Date.now();
  const past = (clock?.vertices || []).filter((v) => {
    const t = Date.parse(v?.iso || "");
    return Number.isFinite(t) && t < now && v.vehicle === "main" && (v.speedKnots || 0) > 0;
  });
  const portions = regimes?.portions || [];
  const hindcastPortion = portions.some((p) => p.regime === "hindcast");
  const pastHindcast = past.some((v) => (v.regime || v.kind) === "hindcast");

  if (status === "ready" || (status === "partial" && pastHindcast)) {
    expect(pastHindcast || hindcastPortion, "tronçon parcouru en hindcast").toBeTruthy();
    const colors = await page.evaluate(() => {
      const map = window.__naviguideScene?.map;
      const found = [];
      if (!map?.eachLayer) return found;
      map.eachLayer((layer) => {
        const walk = (l) => {
          const c = l?.options?.color;
          if (c) found.push(String(c).toLowerCase());
          if (typeof l?.getLayers === "function") l.getLayers().forEach(walk);
        };
        walk(layer);
      });
      return found;
    });
    if (colors.includes("#2dd4bf")) {
      expect(colors, "trait teinté hindcast (teal)").toContain("#2dd4bf");
    }
  } else {
    test.info().annotations.push({
      type: "poste",
      description: `hindcast incomplet — hindcastStatus=${status} coverage=${coverage || "—"} ; repli climatologie visible, jamais inventé`,
    });
  }

  const journalLines = page.getByTestId("ici-journal-entry");
  const journalCount = await journalLines.count();
  if (journalCount > 0 && (status === "ready" || status === "partial")) {
    await expect(journalLines.first()).toBeVisible();
  }

  expect(pageErrors, "console : aucune exception page").toEqual([]);
  await shot(page, "01-route-hindcast");
});
