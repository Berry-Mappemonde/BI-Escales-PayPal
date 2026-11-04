// Aucun bouton nouveau, aucune rangée ajoutée à la barre.
// Sans API : GET /voyage/official sondé ; s'il ne répond pas, annotation.
// Les assertions de barre ne dépendent pas de l'API et restent exigées.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/pw1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

test("la barre film ne gagne ni rangée ni bouton", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 30_000 });
  const switcher = page.getByTestId("film-view-switch");
  await expect(switcher.getByRole("radio")).toHaveCount(2);
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-suivre")).toHaveText("Suivre l’expédition");
  await expect(page.getByTestId("view-tracer")).toHaveText("Tracer");
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  await expect(cinema).toBeVisible();

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(
    official
    && official.ok()
    && String(official.headers()["content-type"] || "").toLowerCase().includes("json"),
  );
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — barre, Suivre et Tracer inchangés",
    });
  }

  await shot(page, "01-suivre");
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "false");
  await expect(switcher.getByRole("radio")).toHaveCount(2);
  await shot(page, "02-tracer");
  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
