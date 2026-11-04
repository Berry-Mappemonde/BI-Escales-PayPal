// Libellé rédigé en texte seul, dans la rangée des commandes.
// EN → Suivre → Revoir → Written : « Nemotron 3.5 Super VL » et « Token Factory »,
// aucune image de logo. Un repli (NIM, OpenRouter) ne dit pas Token Factory.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ed2");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LLM_URL = /nebius|openai|anthropic|openrouter|tokenfactory|api\.nvidia/i;

function filmPayload({ written, source, seconds = 150 }) {
  return {
    status: "ready",
    lang: "en",
    style: written ? "written" : "raw",
    hasWritten: written,
    source: written ? source : "rules",
    reviewedBy: written && source === "nemotron-super" ? "" : undefined,
    model: written ? "nvidia/Nemotron-3.5-Super-VL" : undefined,
    writtenAt: written ? "2026-10-17T10:00:00Z" : undefined,
    targetSeconds: seconds,
    // Écart n° 43 : provenance Tavily rangée au clic Rédigé (port, liens, jamais d'extrait).
    webContext: written ? {
      basis: "tavily",
      port: "La Rochelle",
      fetchedAt: "2026-10-17T10:00:00Z",
      sources: [{
        title: "La Rochelle — Noonsite",
        url: "https://www.noonsite.com/place/france/la-rochelle/",
        domain: "noonsite.com",
      }],
    } : undefined,
    chapters: [{
      text: "On 15 May, Berry-Mappemonde leaves La Rochelle. 432 nautical miles, 9 days at sea.",
      anchors: [{ t: 0, i: 0 }],
    }],
  };
}

async function installFilm(page, source, { delayPost = false } = {}) {
  const cached = new Set();
  await page.route("**/voyage/**/film**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const style = url.searchParams.get("style") || "raw";
    const seconds = Number(url.searchParams.get("seconds") || 0);
    const key = `${url.searchParams.get("lang") || "en"}:${seconds}`;
    if (req.method() === "POST") {
      if (delayPost) await new Promise((resolve) => setTimeout(resolve, 800));
      cached.add(key);
    }
    const serveWritten = req.method() === "POST" || (style === "written" && cached.has(key));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filmPayload({ written: serveWritten, source, seconds })),
    });
  });
}

async function openEnglishFollow(page) {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  const en = page.getByTestId("lang-en");
  if (await en.isVisible().catch(() => false)) await en.click();
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i);
  await expect(page.getByTestId("replay-start")).toBeVisible({ timeout: 15_000 });
}

test("EN, Follow, Replay, Written: text label, no third-party logo", async ({ page }) => {
  test.setTimeout(90_000);
  const llmHits = [];
  page.on("request", (req) => {
    if (LLM_URL.test(req.url())) llmHits.push(req.url());
  });
  await installFilm(page, "nemotron-super", { delayPost: true });
  const official = await probeOfficial(page);
  await openEnglishFollow(page);
  expect(llmHits, "aucun appel LLM depuis le navigateur").toEqual([]);
  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions Rédigé sautées",
    });
    return;
  }

  const replay = page.getByTestId("replay-start");
  if (await replay.isEnabled()) {
    await replay.click();
    const stop = page.getByTestId("replay-stop");
    if (await stop.isVisible().catch(() => false)) await stop.click();
  }

  const written = page.getByTestId("film-style-written");
  await expect(written).toBeEnabled({ timeout: 15_000 });
  await written.click();
  const source = page.getByTestId("film-source");
  // Accept both "Writing…" (ed2WritingNemotron) and "Waiting for writing…" (ed2WritingWait)
  await expect(source).toContainText(/Writing…|Waiting for writing…/, { timeout: 2_000 });
  await expect(source).not.toContainText(/Nemotron|NIM|OpenRouter|Claude|Token Factory|Nebius/i);
  await expect(source).toContainText("AI-generated content", { timeout: 8_000 });
  await expect(source).toContainText("Nemotron 3.5 Super VL");
  await expect(source).toContainText("Token Factory");
  await expect(source).not.toHaveAttribute("hidden", "");
  await expect(source.locator("img")).toHaveCount(0);
  await expect(source.locator("svg")).toHaveCount(0);
  const inCommands = await source.evaluate((el) => Boolean(el.closest("[data-testid='film-commands']")));
  expect(inCommands).toBe(true);
  const web = page.getByTestId("film-web-sources");
  await expect(web).toContainText("Web sources (Tavily) · La Rochelle");
  await expect(web.getByRole("link", { name: "noonsite.com" }))
    .toHaveAttribute("href", "https://www.noonsite.com/place/france/la-rochelle/");
  expect(llmHits).toEqual([]);
  await shot(page, "01-barre-lecture");

  if (await page.getByTestId("replay-start").isEnabled().catch(() => false)) {
    await page.getByTestId("replay-start").click();
    await expect(source).toContainText("Nemotron 3.5 Super VL");
    await expect(source).toContainText("Token Factory");
    await expect(source.locator("img")).toHaveCount(0);
  }
});

test("replis NIM et OpenRouter : pas de Token Factory, pas de logo", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await probeOfficial(page);
  await installFilm(page, "nvidia-gpt-oss-20b");
  await openEnglishFollow(page);
  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions repli sautées",
    });
    return;
  }
  const written = page.getByTestId("film-style-written");
  await expect(written).toBeEnabled({ timeout: 15_000 });
  await written.click();
  const source = page.getByTestId("film-source");
  await expect(source).toContainText("NVIDIA NIM", { timeout: 8_000 });
  await expect(source).not.toContainText("Token Factory");
  await expect(source.locator("img")).toHaveCount(0);
  await expect(source.locator("svg")).toHaveCount(0);
  await shot(page, "02-repli-nim");

  await page.unroute("**/voyage/**/film**").catch(() => {});
  await installFilm(page, "openrouter");
  await page.reload();
  await dismissNotForNav(page);
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  const writtenAgain = page.getByTestId("film-style-written");
  await expect(writtenAgain).toBeEnabled({ timeout: 15_000 });
  await writtenAgain.click();
  const fallback = page.getByTestId("film-source");
  await expect(fallback).toContainText("OpenRouter", { timeout: 8_000 });
  await expect(fallback).not.toContainText("Token Factory");
  await expect(fallback.locator("img")).toHaveCount(0);
});
