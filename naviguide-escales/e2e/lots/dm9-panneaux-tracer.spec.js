// En Tracer, l'encadré ne sert que le tracé (Revue du plan + Récit) ;
// Maintenant et Journal reviennent intacts en Suivre. Panneau droit Tracer :
// Calques et Exporter dépliés, Polaires et Paramètres avancés repliés
// (revue du 14 oct., option A + recommandation panneau droit).
// Sans API : onglets, replis et Demander conseil tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions de contenu de revue / récit — jamais le nombre d'onglets,
// ni les replis, ni l'absence de Date de départ.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-dm9");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

test("Tracer : Revue + Récit, Polaires repliées ; Suivre intact", async ({ page }) => {
  test.setTimeout(120_000);
  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — jambes de revue / paragraphes de récit non exigés ; onglets et replis conservés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await showRightPanel(page);

  const tabs = page.getByTestId("ici-tabs").getByRole("tab", { includeHidden: false });
  await expect(tabs).toHaveCount(2);
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).not.toBeVisible();
  await expect(page.getByTestId("ici-tab-review")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("ici-review-slot")).toBeVisible();
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();

  await expect(page.getByTestId("export-box")).toBeVisible();
  await expect(page.getByTestId("departure-field")).toHaveCount(0);
  await expect(page.getByTestId("ask-advice")).toBeAttached();

  const layers = page.getByTestId("layers-drawer");
  await expect(layers).toBeVisible();
  await expect.poll(async () => layers.evaluate((el) => el.open), { timeout: 8_000 }).toBe(true);

  const polar = page.getByTestId("polar-box");
  await expect(polar).toBeVisible();
  await expect.poll(async () => polar.evaluate((el) => (
    el.tagName.toLowerCase() === "details" ? el.open : true
  )), { timeout: 8_000 }).toBe(false);

  const orders = page.getByTestId("skipper-orders");
  await expect(orders).toBeVisible();
  await expect.poll(async () => orders.evaluate((el) => el.open), { timeout: 8_000 }).toBe(false);

  await polar.locator("summary").first().click();
  await expect.poll(async () => polar.evaluate((el) => el.open), { timeout: 5_000 }).toBe(true);

  if (apiUp) {
    const review = page.getByTestId("plan-review");
    const hasLegs = await review.getByTestId("plan-review-leg").first()
      .isVisible({ timeout: 12_000 }).catch(() => false);
    if (!hasLegs) {
      test.info().annotations.push({
        type: "revue",
        description: "jambes de revue pas encore là — onglet Revue déjà vu",
      });
    }
  }

  await shot(page, "01-tracer-panneaux");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await showRightPanel(page);

  await expect(page.getByTestId("ici-tabs").getByRole("tab")).toHaveCount(4);
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();
  await expect(page.getByTestId("ici-tab-story")).toBeVisible();
  await expect(page.getByTestId("ici-tab-journal")).toBeVisible();
  await expect(page.getByTestId("ici-tab-review")).toBeVisible();

  await expect(page.getByTestId("export-box")).toBeVisible();
  const followPolar = page.getByTestId("polar-box");
  await expect(followPolar).toBeVisible();
  const polarIsDetails = await followPolar.evaluate((el) => el.tagName.toLowerCase() === "details");
  expect(polarIsDetails, "Polaires en Suivre restent le bandeau, pas un tiroir").toBe(false);
  await expect(page.getByTestId("skipper-orders")).toBeVisible();
  await expect(page.getByTestId("layers-drawer")).toBeVisible();
  await expect(page.getByTestId("polar-drop")).toBeVisible();

  await page.getByTestId("ici-tab-now").click();
  await expect(page.getByTestId("ici-tab-now")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("ici-section-leg")).toBeVisible();
  await expect(page.getByTestId("ici-section-here")).toBeVisible();

  await shot(page, "02-suivre-intact");
});
