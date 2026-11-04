// La pilule Rédigé redevient vraie (stock figé, film mocké).
// Sans API : barre, Suivre et pilule Brut tiennent seuls. GET /voyage/official
// sondé ; s'il manque, annotation + saut des assertions hasWritten / étiquette
// — jamais la barre, ni Suivre, ni la pilule Brut, ni l'absence d'appel LLM.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-rg11");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const LLM_URL = /nebius|openai|anthropic|openrouter|tokenfactory|api\.nvidia/i;

const READY_CHAPTER = {
  text: "Le 15 mai, Berry-Mappemonde quitte La Rochelle. 432 milles, 9 jours de mer. Aujourd’hui, le bateau est à Nouméa.",
  anchors: [{ t: 0, i: 0 }, { t: 8, i: 48 }],
};

function filmPayload(written) {
  return {
    status: "ready",
    lang: "fr",
    style: written ? "written" : "raw",
    hasWritten: written,
    source: written ? "nemotron-super-token-factory" : "rules",
    writtenAt: written ? "2026-10-15T12:00:00Z" : undefined,
    chapters: [READY_CHAPTER],
  };
}

async function mockOfficialFilm(page, { written }) {
  await page.route("**/voyage/official/film**", async (route) => {
    const url = new URL(route.request().url());
    const style = url.searchParams.get("style") || "raw";
    const serveWritten = written && style === "written";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filmPayload(serveWritten)),
    });
  });
}

async function openSuivreBar(page) {
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
}

test("Rédigé actif si hasWritten ou film prêt, jamais Rédigé comme source", async ({ page }) => {
  test.setTimeout(90_000);
  const llmHits = [];
  page.on("request", (req) => {
    if (LLM_URL.test(req.url())) llmHits.push(req.url());
  });

  const official = await probeOfficial(page);
  await openSuivreBar(page);

  await expect(page.getByTestId("film-bar")).toBeVisible();
  const rawPill = page.getByTestId("film-style-raw");
  if (await rawPill.isVisible().catch(() => false)) {
    await expect(rawPill).toBeVisible();
  }
  expect(llmHits, "aucun appel LLM depuis le navigateur").toEqual([]);

  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions hasWritten / étiquette sautées ; barre, Suivre, Brut et absence LLM gardés",
    });
    return;
  }

  await page.unroute("**/voyage/official/film**").catch(() => {});
  await mockOfficialFilm(page, { written: true });
  await page.reload();
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const written = page.getByTestId("film-style-written");
  const raw = page.getByTestId("film-style-raw");
  await expect(raw).toBeVisible({ timeout: 15_000 });
  await expect(written).toBeEnabled({ timeout: 15_000 });
  await written.click();
  await expect(written).toHaveAttribute("aria-pressed", "true");
  const source = page.getByTestId("film-source");
  await expect(source).toContainText("Nemotron 3.5 Super VL", { timeout: 8_000 });
  await expect(source).toContainText("Token Factory");
  await expect(source).not.toHaveAttribute("hidden", "");
  expect(llmHits, "aucun appel LLM depuis le navigateur").toEqual([]);
  await shot(page, "01-redige");

  await page.unroute("**/voyage/official/film**").catch(() => {});
  await mockOfficialFilm(page, { written: false });
  await page.reload();
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");

  const writtenOff = page.getByTestId("film-style-written");
  const rawOff = page.getByTestId("film-style-raw");
  const sourceOff = page.getByTestId("film-source");
  await expect(rawOff).toBeVisible({ timeout: 15_000 });
  await expect(writtenOff).toBeEnabled({ timeout: 15_000 });
  await expect(rawOff).toHaveAttribute("aria-pressed", "true");
  await expect(sourceOff).toBeAttached();
  const srcText = (await sourceOff.innerText()).trim();
  await expect(sourceOff).toHaveAttribute("data-llm-source", "rules");
  expect(srcText, "jamais le mot Rédigé comme source").not.toMatch(/Rédigé/i);
  expect(srcText).toMatch(/(^|· )Formulé par les données brutes$/);
  expect(llmHits, "aucun appel LLM depuis le navigateur").toEqual([]);
  await shot(page, "02-brut");
});
