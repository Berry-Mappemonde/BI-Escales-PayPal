// Finitions visibles : langue du document, contraste du thème clair.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showRightPanel } from "../helpers.js";

test("la langue du document suit le choix, le thème clair passe le contraste", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await showRightPanel(page);

  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await page.getByTestId("lang-en").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByTestId("view-suivre")).toHaveText("Follow expedition");
  await page.getByTestId("lang-fr").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");

  const orders = page.getByTestId("skipper-orders");
  await expect(orders).toBeVisible({ timeout: 15_000 });
  if (!(await orders.evaluate((el) => el.open))) {
    await orders.locator("summary").first().click();
  }
  await page.getByTestId("skipper-profile-coastal").click();
  await expect(page.getByTestId("skipper-phrase")).toHaveText("Je parle tôt.");
  await expect(page.getByTestId("skipper-orders-line")).toHaveText("Hs 2,5 m · fond 8 m");
  await expect(page.getByTestId("skipper-coastal-rule")).toHaveText("Côtier conseillé pour < 12 m");

  const kml = page.getByTestId("export-kml");
  await expect(kml).toBeVisible();
  const kmlTitle = await kml.getAttribute("title");
  expect(kmlTitle === "KML de la route en Suivre" || kmlTitle === "Aucune route à exporter").toBeTruthy();

  await page.getByRole("button", { name: "Sombre" }).click();
  await expect(page.getByTestId("sim-root")).toHaveClass(/light-mode/);

  const axe = await new AxeBuilder({ page })
    .include(".naviguide-sidebar-panel")
    .include(".naviguide-film-bar")
    .withTags(["wcag2aa"])
    .analyze();
  const contrast = axe.violations.filter((v) => v.id === "color-contrast");
  expect(contrast, JSON.stringify(contrast.map((v) => ({
    id: v.id,
    nodes: v.nodes.slice(0, 8).map((n) => n.target),
  })))).toEqual([]);
});
