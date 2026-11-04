// Revue visuelle du 29/10 12 h 57, défauts hors PR (PW_WITH_API=1, stock figé) :
// pendant le film, « Autour du bateau » et les alertes suivent le bateau du film
// (jamais Fineveke loin de Wallis, jamais la ZEE Nouvelle-Calédonie à Papeete),
// et l'étiquette de source « règles » n'est plus un mot isolé.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

test.skip(process.env.PW_WITH_API !== "1", "stock figé requis (PW_WITH_API=1)");

for (const lang of ["fr", "en"]) {
  test(`film ${lang} : autour du bateau et ZEE à la position du film`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((l) => {
      localStorage.setItem("naviguide_lang_v4", l);
      try { window.speechSynthesis.speak = () => {}; } catch {}
    }, lang);
    await page.goto("/");
    await dismissNotForNav(page, { timeout: 5000 });
    await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("replay-start").click();
    await expect(page.getByTestId("film-subtitle")).toBeVisible({ timeout: 15_000 });
    await page.waitForFunction(
      () => typeof window.__naviguideFilm?.seekChapter === "function" && (window.__naviguideFilm.chapterCount || 0) > 0,
      null,
      { timeout: 15_000 },
    );
    const panel = page.getByTestId("ici-maintenant");
    await page.waitForTimeout(1200);
    // Début du film (La Rochelle) : rien de Wallis autour du bateau.
    await expect(panel.getByTestId("ici-section-around")).not.toContainText(/Fineveke/);

    const chapters = await page.evaluate(() => (window.__naviguideFilm.chapters || []).map((c) => c.text || ""));
    const idx = chapters.findIndex((t) => /Mata-Utu/.test(t));
    expect(idx, "chapitre Papeete → Mata-Utu").toBeGreaterThanOrEqual(0);
    for (const frac of [0, 0.3]) {
      await page.evaluate(([i, f]) => window.__naviguideFilm.seekChapter(i, f), [idx, frac]);
      await page.waitForTimeout(1500);
      await expect(panel.getByTestId("ici-section-around")).not.toContainText(/Fineveke/);
      await expect(panel.getByTestId("ici-section-alerts")).not.toContainText(/Nouvelle-Calédonie|New Caledonia|Wallis/);
    }

    // Plus de mot « règles » / « rules » isolé dans le panneau.
    const sources = await page.getByTestId("story-source").allInnerTexts();
    for (const s of sources) expect(s.trim()).not.toMatch(/^(règles|rules)$/i);
  });
}
