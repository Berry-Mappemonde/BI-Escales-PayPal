// Journal des moments (serveur). Aucun changement visible.
// Sans API : barre film, Suivre / Simulation / Tracer tiennent seuls.
// GET /voyage/official : sondé ; s'il manque, annotation seulement.
// GET /ici/warm/status et /voyage/official/moments : seulement si l'API répond.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r9a/${name}.webp`,
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

test("Aucun changement visible, trois parcours", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — status / moments non exigés",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("view-suivre")).toBeVisible();
  await expect(page.getByTestId("view-tracer")).toBeVisible();

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).not.toHaveText(/^\s*$/);
  }
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await shot(page, "02-simulation");

  await showLeftPanel(page);
  const draw = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Draw your own route/i });
  await expect(draw).toBeVisible({ timeout: 15_000 });
  await draw.scrollIntoViewIfNeeded();
  // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
  await expect(page.getByTestId("drawing-box")).toBeVisible({ timeout: 15_000 });
  await shot(page, "03-tracer");

  if (apiUp) {
    const status = await page.request.get("/ici/warm/status", { timeout: 5000 }).then((r) => (r.ok() ? r.json() : null)).catch(() => null);
    if (status && Object.prototype.hasOwnProperty.call(status, "moments")) {
      expect(typeof status.moments).toBe("number");
      expect(status.moments).toBeGreaterThanOrEqual(0);
    }
    const moments = await page.request.get("/voyage/official/moments", { timeout: 5000 }).then((r) => (r.ok() ? r.json() : null)).catch(() => null);
    if (moments) {
      expect(Array.isArray(moments.moments)).toBe(true);
      expect(moments.count).toBe(moments.moments.length);
    }
  }

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
