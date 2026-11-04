// Clic Rédigé : la barre affiche Brut et Rédigé sans API.
// GET /voyage/official est sondé ; s'il ne répond pas, les assertions
// qui lisent le film servi sont sautées. Le POST payant n'est pas lancé ici :
// le non-405 est le test Python du processus :8011.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, leaveCinema, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/rx3");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

test("Suivre : Brut et Rédigé sur la barre", async ({ page }) => {
  test.setTimeout(60_000);
  const official = await probeOfficial(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const raw = page.getByTestId("film-style-raw");
  const written = page.getByTestId("film-style-written");
  await expect(raw).toBeVisible({ timeout: 15_000 });
  await expect(written).toBeVisible();
  await expect(raw).toHaveText("Brut");
  await expect(written).toHaveText("Rédigé");
  await expect(raw).toHaveAttribute("aria-pressed", "true");
  await shot(page, "01-suivre");

  if (!official) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions du film servi sautées ; Brut et Rédigé restent",
    });
    return;
  }

  const film = await page.request.get("/voyage/official/film?lang=fr&seconds=150", { timeout: 12_000 }).catch(() => null);
  if (!film || !film.ok()) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official/film absent — lecture du film sautée ; Brut et Rédigé restent",
    });
    return;
  }
  const body = await film.json().catch(() => null);
  expect(body && typeof body === "object", "GET film répond en JSON").toBeTruthy();
  expect(film.status(), "GET film n'est pas un refus de méthode").not.toBe(405);
  await expect(written).toBeVisible();
  await shot(page, "02-film-servi");
});
