// Passage de route : rien à l'écran. La barre, Suivre et Tracer restent.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation
// et retour — les assertions de barre ne sont pas sautées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/vb1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

const LLM_URL = /nebius|openai|anthropic|openrouter|tokenfactory|api\.nvidia/i;

test("Suivre et Tracer : barre inchangée, aucun bouton de vision", async ({ page }) => {
  test.setTimeout(60_000);
  const errors = [];
  const llmHits = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("request", (req) => {
    if (LLM_URL.test(req.url())) llmHits.push(req.url());
  });

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toContainText("Revoir");
  await expect(page.getByRole("button", { name: /^vision$/i })).toHaveCount(0);
  const duration = page.getByTestId("film-duration");
  if (await duration.isVisible().catch(() => false)) {
    await expect(duration.getByRole("button", { name: "2:30", exact: true })).toBeVisible();
    await expect(duration.getByRole("button", { name: "3:00", exact: true })).toBeVisible();
  }
  expect(llmHits, "aucun appel de modèle").toEqual([]);
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
  await shot(page, "01-suivre");

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — aucune lecture de récit ; barre, Suivre et Tracer exigés",
    });
  }

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByRole("button", { name: /^vision$/i })).toHaveCount(0);
  expect(llmHits, "aucun appel de modèle").toEqual([]);
});
