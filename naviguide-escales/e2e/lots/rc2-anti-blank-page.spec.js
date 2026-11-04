import { expect, test } from "@playwright/test";

// Crash-hook checks require a preview built with VITE_NAVIGUIDE_CRASHTEST=1 npm run build.
// The ordinary production-build check below always runs.

test("normal startup renders app content without the root fallback", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("root-error-fallback")).toHaveCount(0);
  await expect.poll(() => page.locator("#root").evaluate((root) => root.children.length)).toBeGreaterThan(0);
});

async function openCrashProbeOrSkip(page, testInfo) {
  await page.goto("/?crashtest=root");
  if (await page.getByTestId("crash-probe-disabled").count() > 0) {
    test.skip(true, "Crash probe disabled; rebuild with VITE_NAVIGUIDE_CRASHTEST=1 npm run build.");
  }
  await expect(page.getByTestId("root-error-fallback")).toBeVisible();
}

test("root error fallback is localized and reloadable when crash hooks are enabled", async ({ page }, testInfo) => {
  await openCrashProbeOrSkip(page, testInfo);
  const fallback = page.getByTestId("root-error-fallback");
  await expect(fallback).toContainText("Une erreur est survenue");
  await expect(page.getByTestId("root-error-reload")).toHaveText("Recharger");
  const reloaded = page.waitForEvent("load");
  await page.getByTestId("root-error-reload").click();
  await reloaded;
  await expect(fallback).toBeVisible();
});

test("root fallback follows the English app preference when crash hooks are enabled", async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "en"));
  await openCrashProbeOrSkip(page, testInfo);
  await expect(page.getByTestId("root-error-fallback")).toContainText("Something went wrong");
  await expect(page.getByTestId("root-error-reload")).toHaveText("Reload");
});

test("panel boundary contains a sidebar crash when crash hooks are enabled", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("naviguide_lang_v4", "fr"));
  await page.goto("/?crashtest=panel");
  if (await page.getByTestId("crash-probe-disabled").count() > 0) {
    test.skip(true, "Crash probe disabled; rebuild with VITE_NAVIGUIDE_CRASHTEST=1 npm run build.");
  }
  await expect(page.getByRole("alert")).toContainText("Ce panneau a rencontré une erreur");
  await expect(page.getByRole("button", { name: "Réessayer le panneau" })).toBeVisible();
});
