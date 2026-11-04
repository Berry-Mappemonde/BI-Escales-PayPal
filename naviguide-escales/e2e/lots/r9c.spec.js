// Le film raconte le journal (ordre de la route, 2 min 30, rédigé prêt).
// Sans API : le brut local tient debout. GET /voyage/official sondé ; s'il
// manque, on annote et on saute seulement les assertions du script serveur.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-rc5/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Revoir : le film raconte le journal, dans l'ordre", async ({ page }) => {
  test.setTimeout(90_000);
  const apiUp = await page.request.get("/voyage/official", { timeout: 5000 }).then((r) => r.ok()).catch(() => false);
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — script serveur /film non exigé",
    });
  }

  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const filmRes = apiUp
    ? page.waitForResponse((res) => /\/voyage\/official\/film/.test(res.url()) && res.ok(), { timeout: 20_000 }).catch(() => null)
    : Promise.resolve(null);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  await filmRes;
  if (apiUp) await page.waitForTimeout(800);

  const { waitFilmReady } = await import("../helpers.js");
  if (apiUp) {
    await waitFilmReady(page);
  }
  const pills = page.getByTestId("film-duration");
  if (apiUp) {
    await expect(pills).toBeVisible({ timeout: 8_000 });
    await expect(pills).toContainText("2:30");
  } else if (await pills.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await expect(pills).toContainText("2:30");
  }

  if (!apiUp) {
    await shot(page, "01-revoir-depart");
    expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
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
  await shot(page, "01-revoir-depart");

  const localText = (await subtitle.innerText()).trim();
  if (localText) {
    await expect(subtitle).toContainText(/Saint-Maur|La Rochelle|Ajaccio|Fort-de-France|Nouméa|départ vers/i);
  }

  if (apiUp) {
    const film = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 8_000 })
      .then((r) => (r.ok() ? r.json() : null))
      .catch(() => null);
    expect(film?.chapters?.length, "GET /voyage/official/film a des chapitres").toBeGreaterThan(0);
    {
      const blob = film.chapters.map((c) => c.text || "").join(" ");
      // Pilules décochées par défaut — le stock peut servir 0, 150 ou 180.
      expect([0, 150, 180], "durée cible du stock").toContain(Number(film.targetSeconds));
      expect(blob, "pas de nm nu").not.toMatch(/\bnm\b/);
      expect(blob, "Saint-Maur").toMatch(/Saint-Maur/);
      expect(blob, "La Rochelle").toMatch(/La Rochelle/);
      expect(blob, "Ajaccio").toMatch(/Ajaccio/);
      const legs = film.chapters
        .map((c) => [(c.fromName || "").toLowerCase(), (c.toName || "").toLowerCase()])
        .filter(([a, b]) => a && b);
      const iSm = legs.findIndex(([a, b]) => a.includes("saint-maur") && b.includes("la rochelle"));
      const iAj = legs.findIndex(([a, b]) => a.includes("la rochelle") && b.includes("ajaccio"));
      expect(iSm, "paire Saint-Maur → La Rochelle").toBeGreaterThanOrEqual(0);
      expect(iAj, "paire La Rochelle → Ajaccio après Saint-Maur").toBeGreaterThan(iSm);
      expect(blob, "pas de saut La Rochelle → Ajaccio").not.toMatch(
        /vers La Rochelle[^.]*\.\s*Arrivée à Ajaccio/i,
      );
      const sea = film.chapters.filter((c) => c.events && c.events.length);
      expect(sea.length, "chapitres avec bulles").toBeGreaterThanOrEqual(1);
      if (typeof film.hasWritten === "boolean" && film.style === "written") {
        expect(film.hasWritten, "rédigé déjà en cache").toBe(true);
      }
      // Une phrase de sous-titre à la fois (RF5 : « quitté Saint-Maur » puis
      // « Départ vers La Rochelle ») : l'ordre se lit sur le chapitre ouvert.
      await page.evaluate(() => window.__naviguideFilm?.seekChapter?.(0));
      await expect.poll(
        async () => page.evaluate(() => String(window.__naviguideFilm?.chapterText || "")),
        { timeout: 12_000 },
      ).toMatch(/Saint-Maur/i);
      const opening = await page.evaluate(() => {
        const live = String(window.__naviguideFilm?.chapterText || "");
        return live;
      });
      const chapterText = opening || film.chapters[0]?.text || "";
      const iSmSub = String(chapterText).toLowerCase().indexOf("saint-maur");
      const iLrSub = String(chapterText).toLowerCase().indexOf("la rochelle");
      expect(iSmSub, "Saint-Maur dans le sous-titre").toBeGreaterThanOrEqual(0);
      expect(iLrSub, "La Rochelle après Saint-Maur dans le sous-titre").toBeGreaterThan(iSmSub);
      await expect(subtitle).toBeVisible();
    }
  }

  await shot(page, "02-paires-suite");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
