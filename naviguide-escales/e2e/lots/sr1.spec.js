// Le mot Simulation n'est plus un libellé. Suivre, Tracer et l'anglais
// tiennent seuls. GET /voyage/official est sondé : s'il ne répond pas,
// l'horloge LIVE est annotée et sautée. Le mot absent, les deux pilules
// et Demander conseil ne dépendent pas de l'API.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, showLeftPanel, showRightPanel } from "../helpers.js";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/sr1");
mkdirSync(recetteDir, { recursive: true });
const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`), type: "webp", quality: 85, fullPage: false,
});

async function assertNoSimulationWord(page, where) {
  const visible = await page.locator("body").innerText();
  expect(visible, `texte visible sans Simulation (${where})`).not.toMatch(/simulation/i);
  const titled = await page.locator("[title], [aria-label]").evaluateAll((els) =>
    els.some((el) => /simulation/i.test(`${el.getAttribute("title") || ""} ${el.getAttribute("aria-label") || ""}`)),
  );
  expect(titled, `title/aria-label sans Simulation (${where})`).toBe(false);
  await expect(page.getByTestId("view-tracer"), `pilule Tracer (${where})`).toHaveText(/^(Tracer|Plot)$/);
  await expect(page.getByTestId("view-tracer")).not.toHaveText(/simulation/i);
}

test("Suivre et Tracer : aucun mot Simulation, Demander conseil toujours là", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiType = official ? (official.headers()["content-type"] || "") : "";
  const apiUp = Boolean(official && official.ok() && apiType.includes("json"));
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — horloge LIVE non exigée ; le mot Simulation et les pilules restent exigés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await showLeftPanel(page);
  await showRightPanel(page);

  await expect(page.getByTestId("view-suivre")).toHaveText(/Suivre l’expédition|Follow expedition/);
  await expect(page.getByTestId("view-simulation")).toHaveCount(0);
  await assertNoSimulationWord(page, "Suivre");
  if (apiUp) {
    await expect(page.getByTestId("film-clock-line")).toContainText("LIVE", { timeout: 10_000 });
  }
  await shot(page, "01-suivre");

  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
  await showLeftPanel(page);
  await expect(page.getByTestId("ask-advice")).toBeAttached();
  await assertNoSimulationWord(page, "Tracer");
  await shot(page, "02-tracer");

  await page.getByTestId("lang-en").click();
  await expect(page.getByTestId("view-suivre")).toContainText(/Follow/i, { timeout: 10_000 });
  await expect(page.getByTestId("view-tracer")).toHaveText("Plot");
  await assertNoSimulationWord(page, "anglais");
  await shot(page, "03-anglais");

  expect(errors, `erreurs de page : ${errors.join(" | ")}`).toEqual([]);
});
