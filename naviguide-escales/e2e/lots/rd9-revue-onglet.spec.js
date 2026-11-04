// Revue du plan en onglet gauche, plus dans le panneau droit ;
// le récit déclamé reprend la revue (verdict, couloirs, saison).
// Sans API : onglet Suivre / Simulation, absence en Tracer, et absence
// dans le panneau droit tiennent seuls (fixture de revue si l'horloge
// n'est pas là).
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions du script serveur — jamais l'onglet, ni le retrait à droite.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rc8");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
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

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible().catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.click();
  await expect(box).toBeVisible({ timeout: 15_000 });
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

async function openReviewTab(page) {
  const tab = page.getByTestId("ici-tab-review");
  await expect(tab).toBeVisible({ timeout: 10_000 });
  await tab.click();
  await expect(page.getByTestId("ici-review-slot")).toBeVisible();
  await expect(page.getByTestId("plan-review")).toBeVisible();
}

test("Revue du plan en onglet gauche, plus à droite", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const officialBody = official && official.ok()
    ? await official.json().catch(() => null)
    : null;
  const apiUp = Boolean(officialBody);
  const hasPoints = Array.isArray(officialBody?.points) && officialBody.points.length > 0;
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — script film / jambes live sautés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await openReviewTab(page);
  const followReview = page.locator("[data-testid='ici-maintenant'] [data-testid='plan-review']");
  await expect(followReview).toBeVisible();
  await expect(followReview.getByText(/Ce que je changerais|What I would change/i)).toBeVisible();
  const reviewProbe = apiUp
    ? await page.request.get("/voyage/official/plan-review", { timeout: 8000 })
      .then((r) => (r.ok() ? r.json() : null)).catch(() => null)
    : null;
  const reviewReady = reviewProbe?.status === "ready" && Array.isArray(reviewProbe?.legs) && reviewProbe.legs.length > 0;
  if (!apiUp || reviewReady) {
    await expect(followReview.getByTestId("plan-review-leg").first()).toBeVisible({ timeout: 10_000 });
    await expect(followReview.getByText(/Aucune jambe à revoir|No leg to review/i)).toHaveCount(0);
    if (hasPoints) {
      await expect(followReview.getByText(/La Rochelle|Ajaccio/i).first()).toBeVisible({ timeout: 20_000 });
      await expect(followReview.getByTestId("plan-review-lanes").first()).toBeVisible();
    } else if (!apiUp) {
      await expect(followReview.getByTestId("plan-review-lanes").first()).toBeVisible();
    }
  } else {
    test.info().annotations.push({
      type: "revue en préparation",
      description: "GET /plan-review pas ready — PLAN_REVIEW_REV, jambes / couloirs sautés ; onglet et retrait à droite gardés",
    });
  }
  await shot(page, "01-onglet");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
  await openReviewTab(page);
  await expect(page.locator("[data-testid='ici-maintenant'] [data-testid='plan-review']").getByText(/Ce que je changerais|What I would change/i)).toBeVisible();
  if (!apiUp || reviewReady) {
    await expect(page.locator("[data-testid='ici-maintenant'] [data-testid='plan-review-leg']").first()).toBeVisible();
  }
  await shot(page, "02-simulation");

  await showToolsPanel(page);
  const right = page.locator(".naviguide-sidebar-panel.right-0");
  await expect(right.getByTestId("plan-review")).toHaveCount(0);
  await expect(right.getByTestId("polar-box")).toBeVisible();
  await expect(right.getByTestId("skipper-orders")).toBeVisible();
  await expect(right.getByTestId("departure-field")).toHaveCount(0);
  await shot(page, "03-panneau-droit");

  const draw = page.getByRole("button", {
    name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i,
  });
  if (await draw.isVisible().catch(() => false)) {
    await draw.scrollIntoViewIfNeeded();
    // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
    const drawing = await page.getByTestId("drawing-box").isVisible({ timeout: 8_000 }).catch(() => false);
    if (drawing) {
      await showLeftPanel(page);
      // DM9 (revue du porteur du 14 oct., § 4.1 option A) : en Tracer, Revue du plan et Récit ;
      // Maintenant et Journal n'ont pas d'objet.
      await expect(page.getByTestId("ici-tab-review")).toBeVisible();
      await expect(page.getByTestId("ici-tab-story")).toBeVisible();
      await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
      await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
      const cancel = page.getByRole("button", { name: /annuler|cancel/i }).first();
      if (await cancel.isVisible().catch(() => false)) await cancel.click();
    }
  }

  if (hasPoints && reviewReady) {
    const reviewRes = await page.request.get("/voyage/official/plan-review", { timeout: 12_000 })
      .catch(() => null);
    expect(reviewRes && reviewRes.ok(), "GET /plan-review 200").toBeTruthy();
    const review = reviewRes ? await reviewRes.json().catch(() => null) : null;
    expect(review?.legs?.length, "jambes dès le semis, sans clock").toBeGreaterThan(0);

    const film = await page.request.get("/voyage/official/film?lang=fr&seconds=0", { timeout: 12_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    const named = (review.legs || []).flatMap((leg) => (
      Array.isArray(leg?.antiShipping?.lanes) ? leg.antiShipping.lanes.filter((n) => typeof n === "string" && n.trim()) : []
    ));
    if (!film?.chapters?.length) {
      test.info().annotations.push({
        type: "film vide",
        description: "GET /film sans chapitres — citation couloir sautée",
      });
    } else {
      const blob = film.chapters.map((c) => c.text || "").join(" ");
      expect(blob, "pas de phrase ATMOS").not.toMatch(FILLER);
      if (named.length) {
        const hit = named.filter((lane) => blob.includes(lane));
        expect(hit.length, `un couloir nommé dans un chapitre (${named.slice(0, 6).join(", ")})`).toBeGreaterThan(0);
      } else {
        test.info().annotations.push({
          type: "pas de couloir",
          description: "plan-review sans couloir nommé — citation sautée",
        });
      }
    }
  }
});
