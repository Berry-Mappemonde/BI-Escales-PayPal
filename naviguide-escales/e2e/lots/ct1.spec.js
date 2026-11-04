// Le contrat de la tête (specs + parcours) dit la même chose
// que l'écran : pilules Suivre / Tracer, plus « Simulation » comme mode.
// Sans API : les pilules tiennent seules. GET /voyage/official est sondé ;
// s'il manque, annotation seulement — aucune assertion n'en dépend.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, probeOfficial } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/lot-ct1");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

test("Pilules Suivre / Tracer, pas Simulation", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });

  const apiUp = Boolean(await probeOfficial(page));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — aucune assertion n'en dépend ; pilules Suivre / Tracer conservées",
    });
  }

  const switcher = page.getByTestId("film-view-switch");
  await expect(switcher.getByRole("radio")).toHaveCount(2);

  // Suivre (accueil) : on lit les deux pilules.
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(switcher.getByRole("radio", { name: /Suivre l’expédition|Follow expedition/ })).toBeVisible();
  await expect(switcher.getByRole("radio", { name: /^(Tracer|Plot)\b/ })).toBeVisible();
  await expect(page.getByTestId("view-tracer")).toHaveText(/^(Tracer|Plot)$/);
  await expect(page.getByTestId("view-tracer")).not.toHaveText(/simulation/i);
  await expect(page.getByTestId("view-suivre")).not.toHaveText(/simulation/i);
  await shot(page, "01-suivre");

  // Tracer : même couple de pilules, plus « Simulation ».
  await page.getByRole("radio", { name: /^(Tracer|Plot)\b/ }).click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(switcher.getByRole("radio", { name: /^(Tracer|Plot)\b/ })).toBeVisible();
  await expect(page.getByTestId("view-tracer")).toHaveText(/^(Tracer|Plot)$/);
  await expect(page.getByTestId("view-tracer")).not.toHaveText(/simulation/i);
  await shot(page, "02-tracer");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
