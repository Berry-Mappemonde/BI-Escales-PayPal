// Première image de la capture : l'application peinte, pas une page blanche.
// Sans API : le film n'est pas lancé. La première image et le titre restent vérifiés.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { captureFirstFrame, isBlankWhiteFrame } from "../../scripts/film-cinematique.mjs";

const recetteDir = join(dirname(fileURLToPath(import.meta.url)), "../../../docs/recette/fv1");
mkdirSync(recetteDir, { recursive: true });

const shot = (page, name) => page.screenshot({
  path: join(recetteDir, `${name}.webp`),
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function dismissNotForNav(page) {
  const ok = page.getByRole("button", { name: /compris|j.ai compris|ok|continuer|accepter|understand|accept/i }).first();
  if (await ok.isVisible({ timeout: 800 }).catch(() => false)) {
    const ack = page.getByTestId("not-for-nav-ack");
    if (await ack.isVisible().catch(() => false)) await ack.check();
    await ok.click();
  }
}

test("La première image n'est pas blanche et le titre reste", async ({ page }) => {
  test.setTimeout(60_000);
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) {
    test.info().annotations.push({
      type: "sans API",
      description: "GET /voyage/official absent — lecture du film sautée ; première image et titre gardés",
    });
  }

  await page.goto("/");
  await dismissNotForNav(page);
  const frame = await captureFirstFrame(page);
  expect(page.url(), "encore about:blank").not.toContain("about:blank");
  expect(frame.via).toBe("app-ready");
  expect(frame.title).toBe("NAVIGUIDE simulator");
  await expect(page).toHaveTitle("NAVIGUIDE simulator");
  expect(await page.title()).toBe(frame.title);
  expect(
    isBlankWhiteFrame(frame.stats.mean, frame.stats.variance),
    `première image blanche ${JSON.stringify(frame.stats)}`,
  ).toBe(false);
  await expect(page.getByTestId("app-ready")).toBeAttached();
  await expect(page.getByTestId("film-bar")).toBeVisible();
  await expect(page.getByTestId("view-suivre")).toBeVisible();
  await expect(page.getByTestId("replay-start")).toBeVisible();

  if (!apiUp) {
    await shot(page, "01-premiere-image");
    return;
  }

  await expect(page.getByTestId("replay-start")).toBeEnabled({ timeout: 30_000 });
  await shot(page, "01-premiere-image");
});
