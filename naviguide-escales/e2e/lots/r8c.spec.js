// Branchement de l'encadré, plus de pop-up hors film.
// Sans API : l'encadré se remplit via la fixture useMoment ; Suivre /
// Simulation / Tracer tiennent seuls. GET /voyage/official : sondé ; s'il
// manque, on annote et on saute seulement les assertions d'horloge / fiche
// enrichie, jamais celles sur l'absence de cartes flottantes.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, openLeftDrawer } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r8c/${name}.webp`,
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
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 15_000 });
}

async function hideLeftPanel(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (!on) await cinema.click();
}

function noFloatingCards(page) {
  return Promise.all([
    expect(page.locator(".naviguide-floating-card[data-testid='moment-now']")).toHaveCount(0),
    expect(page.locator(".naviguide-floating-card[data-testid='moment-free']")).toHaveCount(0),
    expect(page.locator(".leaflet-popup.escale-popup")).toHaveCount(0),
    expect(page.getByTestId("moment-free-listen")).toHaveCount(0),
  ]);
}

test("Un encadré, plus aucune carte flottante hors film", async ({ page }) => {
  test.setTimeout(120_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — horloge officielle / fiche enrichie non exigées",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  await hideLeftPanel(page);
  await noFloatingCards(page);

  await showLeftPanel(page);
  const box = page.getByTestId("ici-maintenant");
  await expect(box).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByTestId("ici-section-here")).toBeVisible();
  await expect(page.getByText(/Ici et maintenant|Here and now/i)).toHaveCount(0);
  await expect(box.locator("h1, h2")).toHaveCount(0);
  await expect(page.getByTestId("listen")).toBeVisible();
  await noFloatingCards(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await hideLeftPanel(page);
  await noFloatingCards(page);
  await showLeftPanel(page);
  await expect(box).toBeVisible();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByText(/À bord, maintenant|Pendant ce temps, autour du bateau/i)).toHaveCount(0);
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).not.toHaveText(/^\s*$/);
  }
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(box).toBeVisible();
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-review")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("ici-review-slot")).toBeVisible();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByTestId("ici-leg-line")).toBeAttached();
  await noFloatingCards(page);
  await expect(page.locator(".leaflet-popup.escale-popup")).toHaveCount(0);
  await shot(page, "02-simulation");

  const draw = page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i });
  await expect(draw).toBeVisible({ timeout: 15_000 });
  await draw.scrollIntoViewIfNeeded();
  // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await noFloatingCards(page);

  await page.getByRole("button", { name: /annuler|cancel/i }).first().click().catch(() => {});
  await showLeftPanel(page);
  const tools = page.locator(".naviguide-sidebar-toggle--right");
  if (await tools.isVisible().catch(() => false)) {
    const theme = page.getByRole("button", { name: /^(clair|light)$/i });
    if (!(await theme.isVisible().catch(() => false))) await tools.click();
    if (await theme.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await theme.click();
      await expect(page.locator(".light-mode")).toBeVisible({ timeout: 5_000 });
      await showLeftPanel(page);
      await expect(page.getByTestId("ici-maintenant")).toBeVisible();
      await expect(page.getByTestId("ici-tabs")).toBeVisible();
    }
  }

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
