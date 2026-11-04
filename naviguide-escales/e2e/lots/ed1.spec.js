// Clic Rédigé seulement : GET ne lance pas de modèle ; l'étiquette
// dit Super, ou Super relu par Ultra. Sans API (CI) : GET /voyage/official
// sondé ; s'il ne répond pas, annotation + saut des assertions film —
// barre, Suivre, Brut et l'absence d'appel Nebius restent.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-ed1");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

const LLM_URL = /nebius|openai|anthropic|openrouter|tokenfactory|api\.nvidia/i;

const RAW_TEXT = "Le 15 mai, Berry-Mappemonde quitte La Rochelle. 432 milles, 9 jours de mer.";
const WRITTEN_TEXT = "Le 15 mai, Berry-Mappemonde laisse La Rochelle. 432 milles, 9 jours de mer.";

function filmPayload({ written, seconds = 150 }) {
  return {
    status: "ready",
    lang: "fr",
    style: written ? "written" : "raw",
    hasWritten: written,
    source: written ? "nemotron-super-token-factory" : "rules",
    writtenAt: written ? "2026-10-17T10:00:00Z" : undefined,
    targetSeconds: seconds,
    chapters: [{
      text: written ? WRITTEN_TEXT : RAW_TEXT,
      anchors: [{ t: 0, i: 0 }],
    }],
  };
}

test("GET sans modèle, clic Rédigé, étiquette Super", async ({ page }) => {
  test.setTimeout(90_000);
  const llmHits = [];
  const filmGets = [];
  page.on("request", (req) => {
    if (LLM_URL.test(req.url())) llmHits.push(req.url());
    let path = "";
    try { path = new URL(req.url()).pathname; } catch { path = req.url(); }
    if (path.includes("/voyage/official/film") || (path.includes("/voyage/") && path.endsWith("/film"))) {
      filmGets.push(`${req.method()} ${req.url()}`);
    }
  });

  const cached = new Set();
  await page.route("**/voyage/**/film**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const style = url.searchParams.get("style") || "raw";
    const seconds = Number(url.searchParams.get("seconds") || 0);
    const key = `${url.searchParams.get("lang") || "fr"}:${seconds}`;
    if (req.method() === "POST") cached.add(key);
    const serveWritten = req.method() === "POST" || (style === "written" && cached.has(key));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filmPayload({ written: serveWritten, seconds })),
    });
  });

  const official = await probeOfficial(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-style-raw")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("film-style-written")).toBeVisible();
  expect(llmHits, "aucun appel LLM depuis le navigateur à l'ouverture").toEqual([]);
  expect(
    filmGets.some((u) => u.startsWith("POST ")),
    "POST film ne part pas à l'ouverture",
  ).toBeFalsy();

  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions clic / étiquette sautées ; barre, Suivre, Brut et absence Nebius gardés",
    });
    await shot(page, "01-clic");
    await shot(page, "02-etiquette");
    return;
  }

  const twoThirty = page.locator("[data-seconds='150']");
  if (await twoThirty.isVisible().catch(() => false)) {
    if ((await twoThirty.getAttribute("aria-pressed")) !== "true") {
      await twoThirty.click();
    }
  }

  const written = page.getByTestId("film-style-written");
  await expect(written).toBeEnabled({ timeout: 15_000 });
  await written.click();
  await expect(written).toHaveAttribute("aria-pressed", "true");
  expect(filmGets.some((u) => u.startsWith("POST ")), "le clic envoie POST film").toBeTruthy();
  const source = page.getByTestId("film-source");
  await expect(source).toContainText("Nemotron 3.5 Super VL", { timeout: 8_000 });
  await expect(source).not.toHaveAttribute("hidden", "");
  const srcText = (await source.innerText()).trim();
  expect(srcText, "jamais le mot Rédigé comme source").not.toMatch(/Rédigé/i);
  expect(llmHits, "aucun appel LLM depuis le navigateur au clic").toEqual([]);
  await shot(page, "01-clic");

  const three = page.locator("[data-seconds='180']");
  if (await three.isVisible().catch(() => false)) {
    await three.click();
    if (await written.isEnabled().catch(() => false)) {
      await written.click();
    }
  }
  await expect(source).toContainText("Nemotron 3.5 Super VL");
  await shot(page, "02-etiquette");

  const beforeReload = filmGets.filter((u) => u.startsWith("POST ")).length;
  await page.reload();
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  const afterReload = filmGets.filter((u) => u.startsWith("POST ")).length;
  expect(afterReload, "recharger n'envoie pas POST film").toBe(beforeReload);
  expect(llmHits).toEqual([]);
});
