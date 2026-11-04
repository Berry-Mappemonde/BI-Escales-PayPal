// Recalcul à blanc : rien à l'écran. La barre, Suivre et Tracer restent.
// « Revoir l'expédition » est sur Suivre. Tracer ne l'affiche pas.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation
// et retour — les assertions de barre ne sont pas sautées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/ry6");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("Suivre et Tracer : aucun bouton de recalcul", async ({ page }) => {
  test.setTimeout(60_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  let apiBody = null;
  if (official && official.ok()) {
    const ct = (official.headers()["content-type"] || "").toLowerCase();
    if (ct.includes("json")) apiBody = await official.json().catch(() => null);
  }
  const apiUp = Boolean(apiBody && typeof apiBody === "object" && !Array.isArray(apiBody));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("replay-start")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toContainText("Revoir");
  await expect(page.getByRole("button", { name: /recalcul/i })).toHaveCount(0);
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /recalcul/i })).toHaveCount(0);
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
  await shot(page, "02-tracer");

  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — lecture du voyage sautée ; barre, Suivre et Tracer exigés",
    });
    return;
  }

  expect(apiBody && typeof apiBody === "object", "GET /voyage/official répond en JSON").toBeTruthy();
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByRole("button", { name: /recalcul/i })).toHaveCount(0);
});
