// Parcours nominal Suivre → Revoir sans ligne rouge.
// GET /voyage/official sondé ; s'il manque, annotation + saut des seules
// assertions d'API (requêtes ≥ 400) — jamais Suivre, ni Revoir, ni
// l'absence d'erreur de page.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

function isAppApi(url) {
  return /\/(voyage|ici|api\/v1|escale|logbook)(?:\/|\?|$)/.test(url);
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

test("Suivre → Revoir sans erreur de page ni requête métier ≥ 400", async ({ page }) => {
  test.setTimeout(90_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — assertions requêtes ≥ 400 sautées",
    });
  }

  const pageErrors = [];
  const bad = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("response", (res) => {
    if (!apiUp || !isAppApi(res.url())) return;
    if (res.status() >= 400) bad.push(`${res.status()} ${res.url()}`);
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await leaveCinema(page);

  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  const revoir = page.getByTestId("replay-start");
  await expect(revoir).toBeVisible();

  if (apiUp && await revoir.isEnabled()) {
    await revoir.click();
    await expect(page.getByTestId("replay-stop")).toBeVisible({ timeout: 12_000 });
  } else if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "Revoir non lancé — film serveur absent",
    });
  }

  expect(pageErrors, `erreurs de page : ${pageErrors.join(" | ")}`).toEqual([]);
  expect(bad, `requêtes ≥ 400 : ${bad.join(" | ")}`).toEqual([]);
});
