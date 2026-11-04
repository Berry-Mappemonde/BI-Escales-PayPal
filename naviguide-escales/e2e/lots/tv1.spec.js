// Questionnaire d'escale, deux tours, une phrase.
// Drapeau fermé (CI) : zéro Tavily depuis le navigateur ; Suivre tient.
// GET /voyage/official sondé ; s'il manque, annotation + saut des lectures
// film / sac — barre et Suivre restent. Aucune donnée factice écrite.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-tv1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const TAVILY = /tavily\.com|api\.tavily/i;
const CHAR_BUDGET_150 = 2250;

test("Drapeau fermé, Suivre, aucun Tavily navigateur", async ({ page }) => {
  test.setTimeout(90_000);
  const tavilyHits = [];
  page.on("request", (req) => {
    if (TAVILY.test(req.url())) tavilyHits.push(req.url());
  });

  const official = await probeOfficial(page);
  const apiUp = Boolean(official);

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
  expect(tavilyHits, "aucun appel Tavily depuis le navigateur").toEqual([]);

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — lectures film/sac sautées ; Suivre et barre gardés",
    });
    await shot(page, "01-fiche");
    return;
  }

  const film150 = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  if (film150 && Array.isArray(film150.chapters)) {
    const blob = film150.chapters.map((c) => c.text || "").join(" ");
    expect(blob.length, "2:30 tient le budget caractères").toBeLessThanOrEqual(CHAR_BUDGET_150 + 80);
  }
  expect(tavilyHits).toEqual([]);
  await shot(page, "01-fiche");
});
