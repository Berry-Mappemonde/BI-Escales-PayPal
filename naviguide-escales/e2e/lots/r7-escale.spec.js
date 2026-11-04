// Fiche d'escale en popup sur le drapeau (et dans Ici, pas here-product).
// Sans API : sonde GET /voyage/official ; saute drapeau / paragraphe /escale.
// La liste n'ouvre plus la fiche ; le drapeau oui.
import { expect, test } from "@playwright/test";
import { centerOnFlag, dismissNotForNav, showLeftPanel, showRightPanel } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r7/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  const res = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!res || !res.ok()) return false;
  const ctype = String(res.headers()["content-type"] || "").toLowerCase();
  return ctype.includes("json");
}

async function showToolsPanel(page) {
  await showRightPanel(page);
  await expect(page.getByTestId("escale-legend")).toBeVisible({ timeout: 10_000 });
}

async function hasAjaccioFlag(page, timeout = 20_000) {
  return page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout }).then(() => true).catch(() => false);
}

/** Clic drapeau Ajaccio : recentre (lâcher le suivi LIVE), reclique le marqueur. */
async function openAjaccioFromFlag(page) {
  if (!(await hasAjaccioFlag(page, 15_000))) return false;
  await centerOnFlag(page, /Ajaccio/);
  const flag = page.locator("[data-testid='waypoint-flag'][data-escale*='Ajaccio']").first();
  if (await flag.isVisible({ timeout: 8_000 }).catch(() => false)) {
    await flag.click({ force: true });
  }
  if (await page.getByTestId("escale-sheet").count()) return true;
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) {
        marker.fire("click");
        return;
      }
    }
  });
  return (await page.getByTestId("escale-sheet").count()) > 0;
}

test("Fiche d'escale sur le drapeau, plus dans le panneau", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — drapeau / paragraphe de fiche non exigés",
    });
  }

  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");

  const openedTracer = await openAjaccioFromFlag(page);
  if (!openedTracer && !apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "aucun drapeau Ajaccio en Tracer — fiche drapeau non exigée",
    });
    await expect(page.getByTestId("here-product").getByTestId("escale-sheet")).toHaveCount(0);
    await shot(page, "01-popup");
  } else {
    const sheet = page.getByTestId("escale-sheet");
    await expect(sheet).toBeVisible({ timeout: 10_000 });
    await expect(sheet).toContainText("Ajaccio");
    await expect(sheet.getByTestId("escale-listen")).toHaveCount(0);
    await expect(sheet.getByRole("button", { name: /écouter|listen/i })).toHaveCount(0);
    await expect(page.getByTestId("escale-close")).toBeVisible();
    await expect(page.getByTestId("here-product").getByTestId("escale-sheet")).toHaveCount(0);

    if (apiUp) {
      const loading = await sheet.getByText(/On rassemble|Loading the sheet/i).isVisible().catch(() => false);
      if (loading) {
        test.info().annotations.push({
          type: "poste",
          description: "fiche encore « On rassemble » (stock figé sans /escale enrichi)",
        });
      } else {
        await expect(sheet).not.toContainText(/On rassemble|Loading the sheet/i);
      }
    }
    await shot(page, "01-popup");

    await page.getByTestId("escale-close").click();
    await expect(page.getByTestId("escale-sheet")).toHaveCount(0);
  }

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("here-product").getByTestId("escale-sheet")).toHaveCount(0);

  await showToolsPanel(page);
  await expect(page.getByTestId("escale-sheet-open")).toHaveCount(0);
  // La liste n'ouvre plus la fiche ; le drapeau oui.
  // En Suivre la caméra LIVE est sur le bateau (Pacifique, 16 oct.) : il faut
  // lâcher le cadrage pending avant de recentrer, sinon le clic rate (CI 3/6).
  const openedSuivre = await openAjaccioFromFlag(page);
  if (!openedSuivre && !apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "drapeau Ajaccio absent en Suivre — fiche Ici / popup non exigée",
    });
    await expect(page.getByTestId("here-product").getByTestId("escale-sheet")).toHaveCount(0);
    await shot(page, "02-suivre");
    return;
  }

  const sheetAgain = page.getByTestId("escale-sheet");
  await expect(sheetAgain).toBeVisible({ timeout: 10_000 });
  await expect(sheetAgain).toContainText("Ajaccio");
  await expect(page.getByTestId("here-product").getByTestId("escale-sheet")).toHaveCount(0);
  await showLeftPanel(page);
  await expect(page.getByTestId("ici-maintenant")).toBeVisible();
  await expect(sheetAgain).toBeInViewport({ timeout: 5_000 });
  await shot(page, "02-suivre");
});
