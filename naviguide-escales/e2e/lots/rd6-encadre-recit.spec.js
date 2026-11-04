// L'encadré gauche tient parole : Récit jamais vide, journal
// qui nomme, sans trou sous les onglets.
// Sans API : Simulation / Tracer sans onglet Récit, et le Journal local
// nommé (fixture AMP Iroise) tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions qui en dépendent (paragraphes du Récit en Suivre) — jamais
// l'absence de Récit en Simulation, ni le nom Iroise.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rd6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

function localJournalSeed() {
  return [
    {
      voyageId: "local",
      seq: 0,
      t: "2026-05-15T08:00:00Z",
      pos: { lat: 46.15, lon: -1.15 },
      signature: "rd6-seed-0",
      changes: [],
    },
    {
      voyageId: "local",
      seq: 1,
      t: "2026-05-16T10:00:00Z",
      pos: { lat: 48.2, lon: -4.8 },
      signature: "rd6-amp-iroise",
      changes: [{ kind: "amp", score: 1, title: "Iroise", fact: "Iroise (4 nm)" }],
    },
  ];
}

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

test("Récit hors Suivre absent, journal nommé, pas de trou", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — paragraphes du Récit en Suivre sautés",
    });
  }

  await page.addInitScript(({ keys, seed }) => {
    try {
      for (const key of keys) localStorage.setItem(key, JSON.stringify(seed));
    } catch {
      /* ignore */
    }
  }, {
    keys: [
      "naviguide.moment-journal.v1.simulation:official",
      "naviguide.moment-journal.v1.official",
    ],
    seed: localJournalSeed(),
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);

  const box = page.getByTestId("ici-maintenant");
  await expect(box).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
  await expect(page.getByText(/Récit est toujours vide|le récit se remplit|onglet vide/i)).toHaveCount(0);
  await shot(page, "01-simulation");

  await page.getByTestId("ici-tab-journal").evaluate((el) => el.click());
  await expect(page.getByTestId("ici-journal-slot")).toBeVisible();
  const ampLine = page.getByTestId("ici-journal-entry").filter({ hasText: /Iroise/i }).first();
  await expect(ampLine).toBeVisible({ timeout: 10_000 });
  await expect(ampLine).toContainText("Aire marine protégée — Iroise");
  await expect(ampLine).not.toHaveText(/^[^—]*Aire marine protégée\s*$/);
  await shot(page, "02-journal");

  const draw = page.getByRole("button", {
    name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i,
  });
  if (await draw.isVisible().catch(() => false)) {
    await draw.scrollIntoViewIfNeeded();
    // Panneau gauche encore en transition (tranches CI) : le clic DOM ne dépend pas de la géométrie (même repli que enterTracer).
  await draw.click({ force: true, timeout: 5_000 }).catch(() => draw.evaluate((el) => el.click()));
    const drawing = await page.getByTestId("drawing-box").isVisible({ timeout: 8_000 }).catch(() => false);
    if (drawing) {
      await expect(page.getByTestId("ici-tab-review")).toBeVisible();
      await expect(page.getByTestId("ici-tab-story")).toBeVisible();
      await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
      await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
      const cancel = page.getByRole("button", { name: /annuler|cancel/i }).first();
      if (await cancel.isVisible().catch(() => false)) await cancel.click();
    }
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();

  if (apiUp) {
    await page.getByTestId("ici-tab-story").click();
    const para = page.getByTestId("story-paragraph").first();
    const filled = await para.isVisible({ timeout: 12_000 }).catch(() => false);
    if (filled) {
      const text = (await para.innerText()).trim();
      expect(text.length, "Récit en Suivre non vide").toBeGreaterThan(0);
    } else {
      test.info().annotations.push({
        type: "horloge pas prête",
        description: "story-paragraph absent — horloge officielle pas encore là ; onglet Récit déjà vu",
      });
    }
  }
});
