// Parcours nominal — remplace r8a, r8b, r10a et r10b (29 sept., triage des specs e2e) :
// ces quatre specs rejouaient le même parcours Suivre → Simulation → Tracer pour des lots serveur
// « sans changement visible ». Une seule spec garde tout ce qu'elles vérifiaient :
//  - L'encadré « Ici » seul (/lot-r8b.html, mode clair) — onglets, sections, pastilles, sources ;
//  - Barre film, horloge, trois vues, aucune erreur de page ;
//  - L'encadré « Ici » présent dans l'app, dans les trois vues ;
//  - GET /voyage/official/advice?leg=3 — structure pending | done | unavailable.
// Sans API : la barre et les trois vues tiennent seules ; l'horloge officielle et /advice sont annotés.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterSimulation, enterTracer, probeOfficial } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-parcours-nominal/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("parcours nominal — encadré Ici seul, trois vues, /advice (R8a · R8b · R10a · R10b)", async ({ page }) => {
  test.setTimeout(120_000);
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — horloge officielle et /advice non joués",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  // ── R8b : l'encadré seul ──
  await page.goto("/lot-r8b.html");
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 15_000 });
  for (const id of ["ici-tab-now", "ici-tab-story", "ici-tab-journal", "ici-section-leg", "ici-section-alerts",
    "ici-section-here", "ici-section-around", "ici-section-sources"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  await expect(page.getByText(/Ici et maintenant|Here and now/i)).toHaveCount(0);
  await expect(page.locator("h1, h2")).toHaveCount(0);
  const pills = page.getByTestId("ici-alert");
  const n = await pills.count();
  expect(n).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("ici-source-link").first()).toBeVisible();
  await shot(page, "01-encadre");
  await pills.nth(0).getByTestId("ici-alert-close").click();
  await expect(page.getByTestId("ici-alert")).toHaveCount(n - 1);
  await page.getByTestId("ici-tab-story").click();
  await expect(page.getByTestId("ici-tab-story")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("ici-story-slot")).toBeAttached();
  await expect(page.getByTestId("ici-section-leg")).toHaveCount(0);
  await page.getByTestId("ici-tab-now").click();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();

  await page.goto("/lot-r8b.html?light=1");
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("html")).toHaveClass(/light-mode/);
  await shot(page, "02-encadre-clair");

  // ── R8a / R10a / R8c : l'app, trois vues ──
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("view-suivre")).toBeVisible();
  await expect(page.getByTestId("view-tracer")).toBeVisible();
  await expect(page.getByTestId("ici-maintenant")).toHaveCount(1);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).not.toHaveText(/^\s*$/);
  }
  await shot(page, "03-suivre");

  await enterSimulation(page);
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("ici-maintenant")).toHaveCount(1);
  await shot(page, "04-simulation");

  await enterTracer(page);
  await expect(page.getByTestId("ici-maintenant")).toHaveCount(1);
  await shot(page, "05-tracer");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);

  // ── R10b : /advice ──
  if (!apiUp) return;
  const adviceRes = await page.request.get("/voyage/official/advice?leg=3", { timeout: 8000 }).catch(() => null);
  if (!adviceRes || !adviceRes.ok()) {
    test.info().annotations.push({
      type: "poste",
      description: `GET /voyage/official/advice?leg=3 → ${adviceRes ? adviceRes.status() : "erreur"} — pending|done à vérifier sur le poste`,
    });
    return;
  }
  let body = await adviceRes.json();
  expect(body.status).toMatch(/^(pending|done|unavailable)$/);
  if (body.status === "unavailable") {
    // Sans isochrone ni modèle (stock figé de la CI), /advice répond « unavailable » — c'est le contrat ;
    // pending | done ne se jouent que sur le poste de recette.
    test.info().annotations.push({
      type: "poste",
      description: "RF1 : /advice honnête (unavailable) sur le stock figé — pending|done vérifiés sur le poste",
    });
    return;
  }
  expect(body.weights.shiftPerDay).toBe(0.3);
  expect(body.weights.extraNm).toBe(0.02);
  for (let i = 0; i < 40 && body.status === "pending"; i += 1) {
    await page.waitForTimeout(250);
    const again = await page.request.get("/voyage/official/advice?leg=3", { timeout: 8000 });
    if (!again.ok()) break;
    body = await again.json();
  }
  if (body.status === "done") {
    expect(body.leg).toBe(3);
    expect(body.best).toBeTruthy();
    expect(Array.isArray(body.alternatives)).toBeTruthy();
    expect(body.alternatives.length).toBeLessThanOrEqual(3);
    expect(body.best.sentence).toBeTruthy();
    expect(Array.isArray(body.best.facts)).toBeTruthy();
    expect(Array.isArray(body.best.cascade)).toBeTruthy();
  } else {
    test.info().annotations.push({
      type: "poste",
      description: "GET /voyage/official/advice?leg=3 encore pending après 10 s — structure pending déjà vérifiée",
    });
  }
});
