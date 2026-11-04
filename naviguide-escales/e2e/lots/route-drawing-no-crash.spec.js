// Entrer dans Tracer ne doit pas boucler les setState (onglet « Aw, Snap ! »).
// Le cas qui tuait l'onglet : zoom différent du plancher monde, puis clic Tracer.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showLeftPanel } from "../helpers.js";

test("Tracer reste vivant après un zoom et accepte un point", async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors = [];
  const depthErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.text().includes("Maximum update depth")) depthErrors.push(msg.text());
  });
  await page.addInitScript(() => {
    window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
      supportsFiber: true,
      inject() { return 1; },
      onCommitFiberRoot() { window.__navCommits = (window.__navCommits || 0) + 1; },
      onCommitFiberUnmount() {},
      onPostCommitFiberRoot() {},
      renderers: new Map(),
    };
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  await page.waitForFunction(() => window.__naviguideScene?.map?.setZoom);
  await page.evaluate(() => window.__naviguideScene.map.setZoom(8));
  await page.waitForTimeout(400);
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  // Le compteur part une fois l'onglet affiché : la rafale du clic n'est pas une boucle.
  await page.evaluate(() => { window.__navCommits = 0; });

  await page.waitForTimeout(800);
  const commits = await page.evaluate(() => window.__navCommits || 0);
  expect(commits, `rendus après Tracer : ${commits}`).toBeLessThan(40);
  expect(depthErrors, "boucle useEffect").toEqual([]);
  expect(pageErrors, `erreurs de page : ${pageErrors.join(" | ")}`).toEqual([]);

  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  await page.evaluate(() => window.__naviguideAddDrawnPoint(46.15, -1.15));
  await showLeftPanel(page);
  await expect(page.getByTestId("drawing-points")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("drawing-points")).toContainText("46.15");

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
});
