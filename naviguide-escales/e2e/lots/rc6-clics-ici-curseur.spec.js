// Clic drapeau → fiche Ici en tête ; clic ligne d'escale → curseur
// qui reste. Sans API : Suivre, panneau Ici et barre film tiennent seuls.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions drapeau / fiche / curseur, jamais Suivre ni l'encadré Ici.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rc6/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function probeOfficial(page) {
  return page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

function leftPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.left-0").first().evaluate((el) => (
    !el.className.includes("-translate-x-full")
  ));
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  if (await leftPanelOpen(page)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect.poll(() => leftPanelOpen(page), { timeout: 10_000 }).toBe(true);
}

function rightPanelOpen(page) {
  return page.locator(".naviguide-sidebar-panel.right-0").first().evaluate((el) => (
    !el.className.includes("translate-x-full")
  ));
}

async function showRightPanel(page) {
  await leaveCinema(page);
  if (await rightPanelOpen(page)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect.poll(() => rightPanelOpen(page), { timeout: 10_000 }).toBe(true);
  await page.waitForTimeout(350);
}

async function waitSceneReady(page) {
  await page.getByTestId("scene-load-mask").waitFor({ state: "hidden", timeout: 45_000 }).catch(() => {});
  await page.waitForFunction(() => Boolean(window.__naviguideScene?.map), null, { timeout: 30_000 }).catch(() => {});
}

async function clickAjaccioFlag(page) {
  const found = await page.waitForFunction(() => {
    const scene = window.__naviguideScene;
    if (!scene?.waypointMarkers) return false;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) return true;
    }
    return false;
  }, null, { timeout: 30_000 }).then(() => true).catch(() => false);
  if (!found) return false;
  await centerOnAjaccio(page);
  const flag = page.locator("[data-testid='waypoint-flag'][data-escale*='Ajaccio']").first();
  if (!(await flag.isVisible({ timeout: 12_000 }).catch(() => false))) return false;
  await flag.click({ force: true });
  return true;
}

/** La caméra Suivre est sur le bateau (Pacifique) : le drapeau d'Ajaccio est hors cadre tant qu'on
 *  ne recentre pas la carte dessus — un clic « force » ne suffit pas hors de la fenêtre (CI, 28 sept.). */
async function centerOnAjaccio(page) {
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return;
    for (const marker of scene.waypointMarkers.values()) {
      if (/Ajaccio/i.test(marker._naviguideWaypoint?.name || "")) {
        scene.map.setView(marker.getLatLng(), 7, { animate: false });
        return;
      }
    }
  });
  await page.waitForTimeout(300);
}

test("Fiche Ici sur drapeau, curseur qui reste sur l'escale", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — drapeau / fiche Ici / curseur non exigés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  const suivre = page.getByTestId("view-suivre");
  if ((await suivre.getAttribute("aria-checked")) !== "true") {
    await suivre.click();
  }
  await expect(suivre).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await waitSceneReady(page);
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("ici-section-here")).toBeVisible();
  await expect(page.getByTestId("ici-tab-now")).toBeVisible();

  let sheetShown = false;
  if (apiUp) {
    const flagged = await clickAjaccioFlag(page);
    expect(flagged, "drapeau Ajaccio présent").toBeTruthy();
    {
      await expect(page.getByTestId("ici-tab-now")).toHaveAttribute("aria-selected", "true");
      const sheet = page.getByTestId("ici-maintenant").getByTestId("escale-sheet");
      await expect(sheet).toBeVisible({ timeout: 10_000 });
      await expect(sheet).toContainText(/Ajaccio/i);
      const here = page.getByTestId("ici-section-here");
      const sheetBox = await here.getByTestId("escale-sheet").boundingBox();
      const source = here.getByTestId("story-source");
      if (await source.isVisible().catch(() => false)) {
        const sourceBox = await source.boundingBox();
        if (sheetBox && sourceBox) {
          expect(sheetBox.y, "fiche d'escale au-dessus de la ligne Nemotron").toBeLessThan(sourceBox.y);
        }
      }
      await sheet.scrollIntoViewIfNeeded();
      sheetShown = true;
    }
  }
  await shot(page, "01-fiche-ici-ajaccio");

  await showRightPanel(page);
  const legend = page.getByTestId("escale-legend");
  const row = legend.locator("li").filter({ hasText: /Ajaccio/i }).first();
  const hasRow = await row.isVisible({ timeout: 10_000 }).catch(() => false);
  if (!hasRow) {
    if (!apiUp) {
      test.info().annotations.push({
        type: "sans API",
        description: "liste Expédition sans Ajaccio — curseur non exigé",
      });
    } else {
      expect(hasRow, "ligne Ajaccio absente de la liste Expédition").toBe(true);
    }
    await shot(page, "02-curseur-ajaccio");
    return;
  }
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — curseur Ajaccio non exigé",
    });
    await shot(page, "02-curseur-ajaccio");
    return;
  }

  await row.scrollIntoViewIfNeeded();
  // La liste n'est plus cliquable — le curseur reste LIVE ; la fiche Ici porte l'escale.
  await centerOnAjaccio(page);
  const flag = page.locator("[data-testid='waypoint-flag'][data-escale*='Ajaccio']").first();
  await expect(flag, "drapeau Ajaccio").toBeVisible({ timeout: 12_000 });
  await flag.click({ force: true });
  const bar = page.getByTestId("film-bar");
  await expect(bar).toContainText(/LIVE/i, { timeout: 8_000 });
  const barText = ((await bar.innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  expect(barText, `curseur LIVE, pas un saut sur Ajaccio : ${barText}`).not.toMatch(/\bAjaccio\b/i);
  if (sheetShown) {
    await expect(page.getByTestId("ici-maintenant").getByTestId("escale-sheet")).toBeVisible();
    await expect(page.getByTestId("ici-maintenant").getByTestId("escale-sheet")).toContainText(/Ajaccio/i);
  }
  await shot(page, "02-curseur-ajaccio");
});
