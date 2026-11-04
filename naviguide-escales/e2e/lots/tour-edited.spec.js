// Lot feat/tour-edited (IDEATION-CRITERES-1005, C2-b renforcé + C4-c) : à l'étape film de la
// visite (?tour=1), « Lire le film Rédigé » lance le rédigé en un clic quand le serveur en a un ;
// sinon le repli Brut est annoncé avant le clic. Aucun POST (aucune écriture Nemotron) depuis la visite.
// Le stock figé n'a pas de rédigé : le film Brut servi est réétiqueté « rédigé » par la route.
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial } from "../helpers.js";

const panel = (page) => page.getByTestId("demo-walkthrough-panel");

/** written: "yes" | "no" | "until-click" (rédigé au sondage, Brut au clic : course côté serveur). */
async function stubFilm(page, written) {
  const state = { posts: 0, writtenGets: 0, clicked: false };
  await page.route("**/voyage/official/film**", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      state.posts += 1;
      await route.fulfill({ status: 500, body: "no POST from the tour" });
      return;
    }
    const url = new URL(req.url());
    const style = url.searchParams.get("style") || "raw";
    let res;
    try {
      res = await route.fetch();
    } catch (error) {
      // Playwright peut fermer la route si le sondage survit à la fin du test.
      if (/test ended|target page, context or browser has been closed|route.*closed/i.test(String(error?.message || error))) return;
      throw error;
    }
    const data = await res.json().catch(() => null);
    if (!data || style !== "written") {
      await route.fulfill({ response: res, json: data ?? undefined });
      return;
    }
    state.writtenGets += 1;
    const serve = written === "yes" || (written === "until-click" && !state.clicked);
    const body = serve
      ? { ...data, style: "written", hasWritten: true, source: "nemotron-super", reviewedBy: "nemotron-ultra" }
      : { ...data, style: "raw", hasWritten: false, source: "rules" };
    await route.fulfill({ response: res, json: body });
  });
  return state;
}

async function openTourAtReplay(page, lang) {
  await page.addInitScript((l) => localStorage.setItem("naviguide_lang_v4", l), lang);
  await page.goto("/?tour=1");
  await dismissNotForNav(page);
  await expect(panel(page)).toHaveAttribute("data-step", "welcome", { timeout: 30_000 });
  await page.getByTestId("demo-walkthrough-next").click();
  await expect(panel(page)).toHaveAttribute("data-step", "models");
  await expect(page.getByTestId("demo-models-thesis")).toHaveText(lang === "en"
    ? "The rules decide when, Nemotron decides how, sources decide what is true."
    : "Les règles décident quand, Nemotron décide comment, les sources décident de ce qui est vrai.");
  for (const id of ["live", "briefing", "layers", "replay"]) {
    await page.getByTestId("demo-walkthrough-next").click();
    await expect(panel(page)).toHaveAttribute("data-step", id);
  }
}

for (const [lang, label, reviewed] of [
  ["fr", "Lire le film Rédigé", "relu par Ultra"],
  ["en", "Play the Edited film", "reviewed by Ultra"],
]) {
  test(`${lang} : un clic sur « ${label} » lance le film rédigé, sans POST`, async ({ page }) => {
    test.setTimeout(120_000);
    test.skip(!(await probeOfficial(page)), "API du stock figé absente (PW_WITH_API=1)");
    const state = await stubFilm(page, "yes");
    await openTourAtReplay(page, lang);
    const edited = page.getByTestId("demo-walkthrough-play-edited");
    await expect(edited).toBeEnabled({ timeout: 45_000 });
    await expect(edited).toHaveText(label);
    await expect(page.getByTestId("demo-edited-source")).toContainText(reviewed);
    await expect(page.getByTestId("demo-edited-fallback")).toHaveCount(0);
    await expect(page.getByTestId("film-style-written")).toHaveAttribute("aria-pressed", "false");
    await page.screenshot({ path: test.info().outputPath(`tour-edited-${lang}.png`) });
    await edited.click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("film-style-written")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("film-source")).toContainText("Nemotron");
    await expect(page.getByTestId("demo-walkthrough-chip")).toBeVisible();
    expect(state.posts).toBe(0);
    await page.getByTestId("demo-walkthrough-chip").click();
    await page.getByTestId("demo-walkthrough-next").click();
    await expect(page.getByTestId("replay-stop")).toHaveCount(0, { timeout: 10_000 });
  });
}

for (const [lang, fallback] of [["fr", /film Brut/], ["en", /Raw film/]]) {
  test(`${lang} : sans rédigé, pas de bouton Rédigé, le repli Brut est annoncé`, async ({ page }) => {
    test.setTimeout(120_000);
    test.skip(!(await probeOfficial(page)), "API du stock figé absente (PW_WITH_API=1)");
    const state = await stubFilm(page, "no");
    await openTourAtReplay(page, lang);
    const play = page.getByTestId("demo-walkthrough-play");
    await expect(play).toBeEnabled({ timeout: 45_000 });
    await expect(page.getByTestId("demo-edited-fallback")).toContainText(fallback);
    await expect(page.getByTestId("demo-walkthrough-play-edited")).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`tour-fallback-${lang}.png`) });
    await play.click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("film-style-raw")).toHaveAttribute("aria-pressed", "true");
    expect(state.posts).toBe(0);
  });
}

test("en : rédigé annoncé puis non servi au clic → le Brut joue, et la visite le dit", async ({ page }) => {
  test.setTimeout(120_000);
  test.skip(!(await probeOfficial(page)), "API du stock figé absente (PW_WITH_API=1)");
  const state = await stubFilm(page, "until-click");
  await openTourAtReplay(page, "en");
  const edited = page.getByTestId("demo-walkthrough-play-edited");
  await expect(edited).toBeEnabled({ timeout: 45_000 });
  state.clicked = true;
  await edited.click();
  await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("film-style-raw")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("demo-walkthrough-chip").click();
  await expect(page.getByTestId("demo-edited-fell-back")).toContainText("the Raw film played instead");
  expect(state.posts).toBe(0);
});
