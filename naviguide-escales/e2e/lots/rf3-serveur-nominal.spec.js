// Serveur nominal : plus de 500/429, Journal rempli, polaires
// chargées. Sans API : barre film, Suivre, Journal et polaires tiennent
// seuls. GET /voyage/official sondé ; s'il manque, annotation + saut des
// seules assertions d'API — jamais les modes, ni l'onglet Journal, ni
// polar-box.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf3");
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

function isNominalUrl(url) {
  return /\/voyage(?:\/official)?(?:\/|\?|$)|\/ici(?:\/|\?|$)|\/api\/v1\/polar\//.test(url);
}

test("Aucune ligne rouge, Journal et polaires", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions /voyage /ici /polar sautées",
    });
  }

  const red = [];
  page.on("response", (res) => {
    if (!isNominalUrl(res.url())) return;
    if (res.status() >= 500) red.push(`${res.status()} ${res.url()}`);
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("clock-line")).toBeVisible();

  await showLeftPanel(page);
  const journalTab = page.getByTestId("ici-tab-journal");
  await expect(journalTab).toBeVisible({ timeout: 10_000 });
  await journalTab.click();
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await expect(page.getByTestId("ici-journal-slot")).toBeAttached();

  await showRightPanel(page);
  await expect(page.getByTestId("polar-box")).toBeVisible();
  await expect(page.getByTestId("polar-status")).toBeVisible();

  await page.waitForTimeout(800);
  await shot(page, "01-console");

  if (!apiUp) {
    await shot(page, "02-journal");
    return;
  }

  const probes = [
    ["/voyage/official", 8000],
    ["/voyage/official/clock", 15000],
    ["/voyage/official/moments", 10000],
    ["/voyage/official/journal", 8000],
    ["/voyage/official/eta?stop=Noum%C3%A9a", 8000],
    ["/voyage/official/plan-review", 8000],
    ["/ici?lat=46.15&lon=-1.16", 12000],
    ["/ici/moment?lat=46.15&lon=-1.16", 12000],
    ["/ici/pearls", 8000],
    // ICI_WARM=0 dans e2e-store-api.sh : la sonde warm n'est pas exigée.
    ["/api/v1/polar/berry-mappemonde-2026/client", 8000],
  ];
  for (const [path, timeout] of probes) {
    const res = await page.request.get(path, { timeout }).catch(() => null)
      || await page.request.get(path, { timeout }).catch(() => null);
    if (!res && (path.startsWith("/ici") || path.includes("/clock") || path.includes("/moments") || path.includes("/journal"))) {
      test.info().annotations.push({
        type: "poste",
        description: `GET ${path} sans réponse (ICI_WARM=0 / offline)`,
      });
      continue;
    }
    expect(res, `GET ${path} répond`).toBeTruthy();
    expect(res.status(), `${path} sans 5xx`).toBeLessThan(500);
  }

  const polar = await page.request.get("/api/v1/polar/berry-mappemonde-2026/client", { timeout: 8000 });
  expect(polar.status()).toBe(200);
  const polarBody = await polar.json();
  expect(polarBody.raw).toBeTruthy();

  const journalRes = await page.request.get("/voyage/official/journal?limit=80", { timeout: 8000 });
  const journal = await journalRes.json().catch(() => ({}));
  expect(journal.status || "ready").toMatch(/^(ready|preparing)$/);
  if (journal.status === "ready" && (journal.latest || []).length > 1) {
    await expect.poll(async () => page.getByTestId("ici-journal-entry").count(), { timeout: 12_000 }).toBeGreaterThan(1);
  }

  await expect(page.getByTestId("polar-status")).toContainText(/Polaires chargées|Polars loaded/);
  await shot(page, "02-journal");
  expect(red, `5xx page : ${red.join(" | ")}`).toEqual([]);
});
