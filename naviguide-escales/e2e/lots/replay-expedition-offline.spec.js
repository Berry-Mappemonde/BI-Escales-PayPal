import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

// À valider hors sandbox : Playwright requires the local preview/API servers.
const TECHNICAL = /overpass_unavailable|Traceback|\bundefined\b|\bNaN\b|\[object Object\]/i;

for (const lang of ["fr", "en"]) {
  for (const viaTour of [false, true]) {
    test(`${lang} : replay réel ${viaTour ? "depuis ?tour=1" : "sans visite guidée"}`, async ({ page }) => {
      test.setTimeout(120_000);
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await page.clock.install();
      await page.addInitScript((locale) => {
        localStorage.setItem("naviguide_lang_v4", locale);
        const synth = window.speechSynthesis;
        if (synth) {
          synth.speak = (utterance) => queueMicrotask(() => utterance.onend?.());
          synth.cancel = () => {};
          Object.defineProperty(synth, "speaking", { configurable: true, get: () => false });
        }
      }, lang);

      await page.goto(viaTour ? "/?tour=1" : `/?lang=${lang}`);
      await dismissNotForNav(page);
      await expect(page.getByTestId("film-bar")).toBeVisible();

      if (viaTour) {
        const tour = page.getByTestId("demo-walkthrough-panel");
        await expect(tour).toHaveAttribute("data-step", "welcome");
        for (const step of ["models", "live", "briefing", "layers", "replay"]) {
          await page.getByTestId("demo-walkthrough-next").click();
          await expect(tour).toHaveAttribute("data-step", step);
        }
      }

      const raw = page.getByTestId("film-style-raw");
      const edited = page.getByTestId("film-style-written");
      let selectedStyle;
      await expect(raw).toHaveText(lang === "fr" ? "Brut" : "Raw");
      await expect(edited).toHaveText(lang === "fr" ? "Rédigé" : "Edited");
      let start;
      if (viaTour) {
        const editedPlay = page.getByTestId("demo-walkthrough-play-edited");
        const rawPlay = page.getByTestId("demo-walkthrough-play");
        const editedFallback = page.getByTestId("demo-edited-fallback");
        if (await editedPlay.count()) {
          start = editedPlay;
          selectedStyle = edited;
          await expect(start).toHaveText(lang === "fr" ? "Lire le film Rédigé" : "Play the Edited film");
        } else {
          // Le panneau ne propose le rédigé que si le service en a réellement fourni un.
          await expect(editedFallback).toBeVisible();
          await expect(rawPlay).toBeEnabled();
          start = rawPlay;
          selectedStyle = raw;
        }
      } else {
        await edited.click();
        const unavailable = page.locator('[data-testid="film-bar"] [role="status"]');
        // Rédigé async (#159) : le statut « Chargement du film… » s'affiche pendant le job ;
        // on attend l'état terminal (rédigé servi ou indisponible), pas un statut quelconque.
        const UNAVAILABLE = /momentanément indisponible|temporarily unavailable/i;
        await expect.poll(async () => (
          await edited.getAttribute("aria-pressed") === "true"
          || (await unavailable.isVisible() && UNAVAILABLE.test(await unavailable.innerText()))
        ), { timeout: 45_000 }).toBe(true);
        if (await edited.getAttribute("aria-pressed") === "true") {
          start = page.getByTestId("replay-start");
          selectedStyle = edited;
        } else {
          await expect(unavailable).toContainText(/momentanément indisponible|temporarily unavailable/i);
          await raw.click();
          await expect(raw).toHaveAttribute("aria-pressed", "true");
          start = page.getByTestId("replay-start");
          selectedStyle = raw;
        }
      }
      await expect(start).toBeEnabled({ timeout: 45_000 });
      await start.click();
      await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 15_000 });
      await expect(selectedStyle).toHaveAttribute("aria-pressed", "true");
      await expect.poll(() => page.evaluate(() => Number.isFinite(window.__naviguideFilm?.startedAt)), {
        timeout: 15_000,
      }).toBe(true);

      const subtitle = page.getByTestId("film-subtitle");
      await expect(subtitle).toBeVisible();
      await expect.poll(() => subtitle.innerText()).toMatch(/\S/);
      const firstChapterText = await subtitle.innerText();
      const firstChapter = await page.evaluate(() => window.__naviguideFilm?.chapterIdx ?? 0);
      expect(firstChapterText).not.toMatch(TECHNICAL);

      // Hors ligne, l'API sert le film brut à partir des règles. La provenance
      // reste dans le DOM même si le style actif masque le badge.
      const source = page.getByTestId("film-source");
      await expect(source).toHaveAttribute("data-llm-source", "rules");
      await expect(source).toHaveAttribute("data-ai-generated", "false");
      if (selectedStyle === edited) {
        await expect(source).toBeVisible();
      } else {
        await expect(source).toBeHidden();
      }

      // Le film tourne dans une boucle requestAnimationFrame pilotée par
      // performance.now(). Un chapitre peut dépasser largement 2 secondes :
      // avance en tranches virtuelles et vérifie aussi que la boucle a tourné.
      let progress = await page.evaluate(() => ({
        chapter: window.__naviguideFilm?.chapterIdx ?? 0,
        elapsed: window.__naviguideFilm?.elapsed ?? 0,
      }));
      for (let i = 0; i < 18 && progress.chapter <= firstChapter; i += 1) {
        await page.clock.runFor(5_000);
        progress = await page.evaluate(() => ({
          chapter: window.__naviguideFilm?.chapterIdx ?? 0,
          elapsed: window.__naviguideFilm?.elapsed ?? 0,
        }));
      }
      expect(progress.elapsed).toBeGreaterThan(0);
      expect(progress.chapter).toBeGreaterThan(firstChapter);
      const chapterText = await subtitle.innerText();
      expect(chapterText).not.toBe(firstChapterText);
      expect(chapterText).not.toMatch(TECHNICAL);

      await page.getByTestId("replay-stop").click();
      await expect(page.getByTestId("replay-start")).toBeVisible();
      await expect(consoleErrors, "erreurs console").toEqual([]);
      await expect(pageErrors, "erreurs page").toEqual([]);
    });
  }
}
