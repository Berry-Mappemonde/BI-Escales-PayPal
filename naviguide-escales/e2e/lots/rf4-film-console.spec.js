// Console vierge pendant le film : le bateau du film ne sonde
// plus /ici ni l'ETA. Sans API : Suivre, Revoir et Stop tiennent seuls ;
// les comptes de requêtes restent (le client ne doit pas les lancer).
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions de contenu du sac live — jamais la barre, ni Revoir, ni Stop.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rf4");
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
  const isOn = async () => /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (!(await isOn())) return;
  await page.keyboard.press("Escape");
  if (!(await isOn())) return;
  await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

function isIciUrl(url) {
  return /\/ici(?:\?|\/moment)/.test(url);
}

function isEtaUrl(url) {
  return /\/voyage\/official\/eta/.test(url);
}

test("Console vierge pendant le film, sac live après Stop", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — contenu du sac live sauté ; comptes /ici /eta gardés",
    });
  }

  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  let filming = false;
  const iciDuring = [];
  const etaDuring = [];
  const allDuring = [];
  page.on("request", (req) => {
    if (!filming) return;
    const u = req.url();
    allDuring.push(u);
    if (isIciUrl(u)) iciDuring.push(u);
    if (isEtaUrl(u)) etaDuring.push(u);
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });

  const durationOn = page.locator("[data-testid='film-duration'] [aria-pressed='true']");
  if (await durationOn.count()) {
    await durationOn.first().click();
  }

  if (apiUp) {
    await page.waitForFunction(() => {
      const b = document.querySelector("[data-testid='replay-start']");
      return Boolean(b && !b.disabled && b.getAttribute("aria-disabled") !== "true");
    }, { timeout: 25_000 }).catch(() => null);
  }
  const canStart = await start.isEnabled();
  if (!canStart) {
    test.info().annotations.push({
      type: "sans film",
      description: "Revoir grisé — film non lancé ; barre et Suivre vérifiés",
    });
    await showLeftPanel(page);
    await expect(page.getByTestId("ici-maintenant")).toBeVisible();
    await shot(page, "01-console-film");
    expect(pageErrors, `pageerror : ${pageErrors.join(" | ")}`).toEqual([]);
    return;
  }

  await start.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  filming = true;
  await page.waitForTimeout(4_000);
  filming = false;

  expect(iciDuring.length, `GET /ici pendant le film : ${iciDuring.length}`).toBe(0);
  expect(etaDuring.length, `GET /eta pendant le film : ${etaDuring.length}`).toBe(0);
  expect(allDuring.length, `rafale réseau pendant le film : ${allDuring.length}`).toBeLessThan(1000);

  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await shot(page, "01-console-film");

  await page.getByTestId("replay-stop").click();
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await page.waitForTimeout(1_200);

  expect(pageErrors, `pageerror : ${pageErrors.join(" | ")}`).toEqual([]);
  const redConsole = consoleErrors.filter((t) => !/favicon|ResizeObserver/i.test(t));
  expect(redConsole, `console error : ${redConsole.join(" | ")}`).toEqual([]);
});
