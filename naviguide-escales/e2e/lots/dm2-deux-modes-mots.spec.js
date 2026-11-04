// Les mots des deux modes (après DM1) :
// chaque texte visible ou lu dit Suivre / Tracer (FR) et Follow / Plot (EN).
// GetByRole lit Tracer|Plot (libellé livré), pas Simulation comme mode.
// Sans API : tout tient seul (textes, commutateur, ordres skipper, langue) —
// GET /voyage/official est sondé mais aucune assertion n'en dépend.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial, showLeftPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm2");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

// Pilule et textes visibles : Suivre / Tracer (FR) ou Follow / Plot (EN).
// On lit le libellé livré (getByRole Tracer|Plot), on ne cherche
// plus « Simulation » comme mot à l'écran. Casse si la pilule redevient Simulation.
async function expectModePills(page, where) {
  const switcher = page.getByTestId("film-view-switch");
  await expect(
    switcher.getByRole("radio", { name: /Suivre l’expédition|Follow expedition/ }),
    `pilule Suivre (${where})`,
  ).toBeVisible();
  await expect(
    switcher.getByRole("radio", { name: /^(Tracer|Plot)\b/ }),
    `pilule Tracer (${where})`,
  ).toBeVisible();
  await expect(page.getByTestId("view-tracer"), `pilule ≠ Simulation (${where})`).toHaveText(/^(Tracer|Plot)$/);
  await expect(page.getByTestId("view-tracer")).not.toHaveText(/simulation/i);
  const titled = await page.locator("[title], [aria-label]").evaluateAll((els) =>
    els.some((el) => /simulation/i.test(`${el.getAttribute("title") || ""} ${el.getAttribute("aria-label") || ""}`)),
  );
  expect(titled, `title/aria-label sans Simulation (${where})`).toBe(false);
}

async function showToolsPanel(page) {
  await leaveCinema(page);
  const orders = page.getByTestId("skipper-orders");
  if (await orders.isVisible({ timeout: 1500 }).catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.evaluate((el) => el.click());
  await expect(orders).toBeVisible({ timeout: 15_000 });
}

test("Suivre / Tracer dans chaque texte, aucun « Simulation » à l'écran (FR puis EN)", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await probeOfficial(page); // sonde seulement : aucune assertion ne dépend de l'API

  // (a) Accueil FR : le commutateur s'annonce « Suivre l'expédition ou Tracer » ;
  // l'info-bulle de la pilule Tracer dit Tracer, jamais Simulation.
  await expect(page.getByTestId("film-view-switch")).toHaveAttribute(
    "aria-label", "Suivre l’expédition ou Tracer",
  );
  await expect(page.getByTestId("view-tracer")).toHaveAttribute(
    "title", "Tracer — jouer la route Berry-Mappemonde ou la vôtre : date de départ, Play, calculs",
  );

  // (b) Panneaux ouverts, accueil FR : pilules Suivre / Tracer.
  await showLeftPanel(page);
  await expectModePills(page, "accueil FR");
  await shot(page, "01-accueil");

  // (c) Tracer + panneau droit : les ordres skipper disent « cette jambe (Tracer) ».
  await page.getByRole("radio", { name: /^(Tracer|Plot)\b/ }).click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showToolsPanel(page);
  await page.getByTestId("skipper-orders").evaluate((el) => { el.open = true; });
  await expect(page.getByTestId("skipper-horizon")).toContainText("cette jambe (Tracer)");
  await expectModePills(page, "Tracer FR, panneaux ouverts");

  // (d) Anglais : Follow / Plot partout, toujours aucun « Simulation ».
  const en = page.getByTestId("lang-en");
  await expect(en).toBeVisible({ timeout: 10_000 });
  await en.click();
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i, { timeout: 10_000 });
  await expect(page.getByTestId("film-view-switch")).toHaveAttribute(
    "aria-label", "Follow the expedition or Plot",
  );
  await expect(page.getByTestId("view-tracer")).toHaveText("Plot");
  await expect(page.getByTestId("skipper-horizon")).toContainText("this leg (Plot)");
  await expectModePills(page, "Tracer EN");

  // (e) Retour à l'accueil (Suivre) en anglais pour la capture.
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page); // Suivre rouvre le cinéma
  await showLeftPanel(page);
  await expectModePills(page, "accueil EN");
  await shot(page, "02-en");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
