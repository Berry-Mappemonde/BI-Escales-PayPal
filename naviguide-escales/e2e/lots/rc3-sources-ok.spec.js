// Ligne Sources : des noms de producteurs, plus le statut « ok ».
// Sans API : page encadré /lot-r8b.html (fixture) + section Sources de l'app.
// Avec API : Suivre, la ligne du Moment ne contient pas « ok ».
// Ne pas affaiblir les assertions qui n'ont pas besoin de l'API.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rc3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

const STATUS_TOKEN = /(?:^|[·,;|/])\s*(ok|error|pending)\s*(?=$|[·,;|/])/i;
const PRODUCER = /VLIZ|Open-Meteo|CDSE|EMODnet|OpenStreetMap|Atlas BI|Blue Intelligence|MarineRegions|GEBCO/i;

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

async function probeOfficial(page) {
  for (let i = 0; i < 8; i += 1) {
    const ok = await page.request.get("/voyage/official", { timeout: 4000 }).then((r) => r.ok()).catch(() => false);
    if (ok) return true;
    await page.waitForTimeout(400);
  }
  return false;
}

function sourcesText(raw) {
  return String(raw || "").replace(/\s+/g, " ").trim();
}

test("Sources : noms de producteurs, plus « ok »", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await probeOfficial(page);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — ligne Sources du Moment live non exigée",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/lot-r8b.html");
  await expect(page.getByTestId("ici-maintenant")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ici-section-sources")).toBeVisible();
  const fixtureLine = page.getByTestId("ici-sources-line");
  await expect(fixtureLine).toBeVisible();
  const fixtureText = sourcesText(await fixtureLine.innerText());
  expect(fixtureText, `Sources encadré : ${fixtureText}`).toMatch(PRODUCER);
  expect(fixtureText, `Sources encadré : ${fixtureText}`).not.toMatch(STATUS_TOKEN);
  expect(fixtureText, `Sources encadré : ${fixtureText}`).not.toMatch(/(^|\s)ok(\s|$)/i);
  await shot(page, "01-encadre-sources");

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await page.getByTestId("ici-tab-now").click();
  const sourcesSection = page.getByTestId("ici-section-sources");
  await expect(sourcesSection).toBeVisible();
  await sourcesSection.scrollIntoViewIfNeeded();
  const followLine = page.getByTestId("ici-sources-line");
  await expect(followLine).toHaveCount(1);
  const followText = sourcesText(await followLine.innerText());
  expect(followText, `Sources Suivre : ${followText}`).not.toMatch(STATUS_TOKEN);
  expect(followText, `Sources Suivre : ${followText}`).not.toMatch(/(^|\s)ok(\s|$)/i);
  if (apiUp) {
    let live = followText;
    if (!live) {
      await page.waitForTimeout(4000);
      live = sourcesText(await followLine.innerText());
    }
    if (live) {
      expect(live, `Sources Suivre (API) : ${live}`).toMatch(PRODUCER);
      expect(live, `Sources Suivre (API) : ${live}`).not.toMatch(STATUS_TOKEN);
    } else {
      test.info().annotations.push({
        type: "Sources",
        description: "ligne Sources vide après attente — Moment live non rempli, pas de « ok »",
      });
    }
  } else {
    test.info().annotations.push({
      type: "sans API",
      description: "noms de producteurs du Moment live non exigés",
    });
  }
  await shot(page, "02-suivre-sources");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
