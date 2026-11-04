// Deux modes à l'écran : Suivre | Tracer (décision du porteur du
// 29 sept.). Tracer = l'ex-Simulation sur
// la route Berry-Mappemonde, avec la carte route sous les yeux : pilules
// Berry-Mappemonde | <ma route>, « Tracer votre propre route », Importer.
// Le mode interne (VIEW_SIMULATION) ne change pas (DM3 renomme).
// Sans API : (a)-(d) tiennent seuls ; le tracé d'une route perso (jouée via
// /voyage) est annoté et sauté — capture 03 sur le poste.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm1");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

// Signature de la pilule active de la carte route (classe pillOn de BerryCard).
const PILL_ON = /bg-blue-600\/30/;

test("Deux pilules Suivre | Tracer, Tracer joue Berry, carte route toujours là", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 15_000 });
  const apiUp = Boolean(await probeOfficial(page));

  // (a) La barre film montre deux pilules exactement : Suivre et Tracer
  // (libellé livré — CT1). getByRole lit Tracer, pas Simulation.
  const switcher = page.getByTestId("film-view-switch");
  const pills = switcher.getByRole("radio");
  await expect(pills).toHaveCount(2);
  await expect(switcher.getByRole("radio", { name: /Suivre l’expédition|Follow expedition/ })).toBeVisible();
  await expect(switcher.getByRole("radio", { name: /^(Tracer|Plot)\b/ })).toBeVisible();
  await expect(page.getByTestId("view-suivre")).toHaveText(/Suivre l’expédition|Follow expedition/);
  await expect(page.getByTestId("view-tracer")).toHaveText(/^(Tracer|Plot)$/);
  await expect(page.getByTestId("view-tracer")).not.toHaveText(/simulation/i);
  expect(await page.getByTestId("view-simulation").count(), "ancienne pilule view-simulation").toBe(0);
  await shot(page, "01-deux-pilules");

  // (b) Clic Tracer → aria-checked ; Play / vitesses ; carte route avec
  // pilules Berry-Mappemonde | « Tracer votre propre route » et Importer.
  // Le dessin est ouvert tout de suite (la pilule de tracé est active).
  // Plus de champ Date de départ en Tracer (il reste en Suivre).
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("departure-field")).toHaveCount(0);
  await expect(page.getByTestId("film-bar").getByTitle(/^(Lecture|Play)$/)).toBeVisible();
  await expect(page.getByTestId("film-speed")).toBeVisible();
  const berryPill = page.getByTestId("route-switch-berry");
  await expect(berryPill).toBeVisible({ timeout: 10_000 });
  const drawPill = page.getByTestId("route-switch-draw");
  await expect(drawPill).toHaveText(/Tracer votre propre route|Draw your own route/);
  expect((await drawPill.getAttribute("class")) || "", "pilule Tracer votre propre route active").toMatch(PILL_ON);
  expect((await berryPill.getAttribute("class")) || "", "pilule Berry visible, pas le dessin").not.toMatch(PILL_ON);
  await expect(page.getByText(/Choisissez votre point de départ|Choose your starting point/).first()).toBeVisible();
  await expect(page.getByTestId("route-import")).toBeVisible();
  await shot(page, "02-tracer-berry");

  // Tracer : Revue du plan + Récit seulement (Maintenant / Journal masqués).
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();

  // (c) Recalculer / Demander conseil : présents (actifs ou non, comme aujourd'hui).
  await expect(page.getByTestId("ask-advice")).toBeAttached();

  // (d) Retour Suivre → horloge LIVE ; carte route de main (bouton du bas,
  // pas de pilules sans route perso).
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-clock-line")).toContainText("LIVE", { timeout: 10_000 });
  await showLeftPanel(page);
  await expect(page.getByTestId("route-switch-berry")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Berry-Mappemonde.*Tracer votre propre route|Draw your own route/i })).toBeVisible();

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);

  // Tracé d'une route perso : elle se joue par /voyage — sans API, on saute.
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — tracé + pilules Berry | <ma route> non joués (capture 03 sur le poste)",
    });
    return;
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("route-switch-draw").click();
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function", { timeout: 10_000 });
  await page.evaluate(() => window.__naviguideAddDrawnPoint(46.1, -1.5)); // large de La Rochelle
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 1, { timeout: 10_000 });
  await page.evaluate(() => window.__naviguideAddDrawnPoint(41.9, 8.7)); // Ajaccio
  await page.waitForFunction(() => (window.__naviguideDrawn?.points?.length || 0) >= 2, { timeout: 10_000 });
  const finish = page.getByRole("button", { name: /terminer|finish/i });
  await expect(finish).toBeEnabled({ timeout: 20_000 });
  await finish.click();

  // Terminer entre en Tracer : pilules Berry | <ma route>, la perso active.
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  const customPill = page.getByTestId("route-switch-custom");
  await expect(customPill).toBeVisible({ timeout: 10_000 });
  await expect(customPill).toHaveText(/Route personnalisée|Custom Route/);
  expect((await customPill.getAttribute("class")) || "", "pilule perso active").toMatch(PILL_ON);
  await shot(page, "03-tracer-ma-route");

  // Berry → retour à la route officielle, sans changer de vue.
  await page.getByTestId("route-switch-berry").click();
  await expect.poll(async () => (await page.getByTestId("route-switch-berry").getAttribute("class")) || "", {
    timeout: 8_000,
  }).toMatch(PILL_ON);
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
});
