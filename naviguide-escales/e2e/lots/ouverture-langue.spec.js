import { test, expect } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } });

test("sans choix enregistré, l'écran s'ouvre en anglais", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByTestId("view-suivre")).toHaveText("Follow expedition");
  const stored = await page.evaluate(() => ({
    v4: localStorage.getItem("naviguide_lang_v4"),
    v3: localStorage.getItem("naviguide_lang_v3"),
  }));
  expect(stored.v4).toBeNull();
  expect(stored.v3).toBeNull();
});

test("une préférence française déjà enregistrée est respectée", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("naviguide_lang_v4", "fr");
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(page.getByTestId("view-suivre")).toHaveText("Suivre l’expédition");
});

test("une préférence française sur l'ancienne clé est migrée et respectée", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("naviguide_lang_v3", "fr");
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(page.getByTestId("view-suivre")).toHaveText("Suivre l’expédition");
  const stored = await page.evaluate(() => ({
    v4: localStorage.getItem("naviguide_lang_v4"),
    v3: localStorage.getItem("naviguide_lang_v3"),
  }));
  expect(stored.v4).toBe("fr");
  expect(stored.v3).toBeNull();
});
