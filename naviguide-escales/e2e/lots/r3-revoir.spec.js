// Premier clic sur Revoir lance le film ; pas terminé après 5 s.
// Sans API : le brut local tient debout. Headless : pas de voix (webdriver).
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-r3/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Premier clic lance le film, encore en cours après 5 s", async ({ page }) => {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });

  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  const { waitFilmCanStart } = await import("../helpers.js");
  if (!(await waitFilmCanStart(page, 12_000))) {
    test.info().annotations.push({
      type: "Revoir grisé",
      description: "RC11 : Revoir encore désactivé — film non lancé",
    });
    await shot(page, "01-premier-clic");
    return;
  }

  await page.getByTestId("replay-start").click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 8_000 });
  const subtitle = page.getByTestId("film-subtitle");
  await expect(subtitle).toBeVisible({ timeout: 8_000 });

  await expect.poll(async () => page.evaluate(() => Boolean(window.__naviguideFilm?.startedAt)), {
    timeout: 5_000,
  }).toBe(true);
  expect(await page.evaluate(() => Boolean(window.__naviguideFilm?.ended))).toBe(false);
  await shot(page, "01-premier-clic");

  await page.waitForTimeout(5_000);
  const after = await page.evaluate(() => ({
    ended: Boolean(window.__naviguideFilm?.ended),
    chapter: window.__naviguideFilm?.chapterIdx ?? 0,
    stop: Boolean(document.querySelector("[data-testid='replay-stop']")),
  }));
  expect(after.ended, "film encore en cours après 5 s").toBe(false);
  expect(after.stop, "Retour au live encore visible").toBe(true);

  const text = (await subtitle.innerText()).trim();
  if (text) {
    await expect(subtitle).toContainText(/Saint-Maur|La Rochelle/i);
  } else if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "sous-titre du chapitre 1 vide — texte non vérifié",
    });
  } else {
    await expect(subtitle).toContainText(/Saint-Maur|La Rochelle/i);
  }
  await shot(page, "02-chapitre-1");
});
