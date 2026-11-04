// Panneau gauche stable : le chat ne saute pas pendant une lecture.
import { expect, test } from "@playwright/test";
import { dismissNotForNav } from "../helpers.js";

const shot = (page, name) => page.screenshot({
  path: `../docs/recette/lot-n/${name}.webp`,
  type: "webp",
  quality: 85,
  fullPage: false,
});

async function showLeftPanel(page) {
  const chat = page.getByTestId("logbook-chat");
  if (await chat.isVisible().catch(() => false)) return;
  const cinema = page.getByRole("button", { name: /^cinéma$/i });
  if (await cinema.isVisible().catch(() => false)) await cinema.click();
  if (await chat.isVisible({ timeout: 4000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(chat).toBeVisible({ timeout: 15_000 });
}

async function showToolsPanel(page) {
  const theme = page.getByRole("button", { name: /^(sombre|clair|dark|light)$/i });
  if (await theme.isVisible().catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--right").click();
  await expect(theme).toBeVisible({ timeout: 10_000 });
}

test("Chat immobile pendant une lecture Suivre ; sombre puis clair", async ({ page }) => {
  test.setTimeout(45_000);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-clock-line")).toBeVisible({ timeout: 20_000 });

  const { leaveCinema, showLeftPanel: openLeft, showRightPanel } = await import("../helpers.js");
  await page.getByTestId("view-suivre").click();
  await expect(page.getByTestId("view-suivre")).toHaveAttribute("aria-checked", "true");
  await leaveCinema(page);
  await openLeft(page);

  const chat = page.getByTestId("logbook-chat");
  await expect(chat).toBeVisible({ timeout: 15_000 });
  const topBefore = await chat.evaluate((el) => el.getBoundingClientRect().top);

  const start = page.getByTestId("replay-start");
  if (await start.isEnabled().catch(() => false)) {
    await start.click();
    await page.waitForTimeout(2_000);
  }

  await expect(chat).toBeVisible();
  const topAfter = await chat.evaluate((el) => el.getBoundingClientRect().top);
  expect(topAfter, `chat.top avant=${topBefore} après=${topAfter}`).toBe(topBefore);
  await shot(page, "01-sombre");

  await showRightPanel(page);
  const theme = page.getByRole("button", { name: /^(sombre|clair|dark|light)$/i });
  await expect(theme).toBeVisible({ timeout: 8_000 });
  await theme.evaluate((el) => el.click());
  await expect(page.locator(".light-mode")).toBeVisible({ timeout: 5_000 });
  await page.locator(".naviguide-sidebar-toggle--right").evaluate((el) => el.click());
  await showLeftPanel(page);
  await expect(chat).toBeVisible();
  const topLight = await chat.evaluate((el) => el.getBoundingClientRect().top);
  expect(topLight, `chat.top clair=${topLight} sombre=${topBefore}`).toBe(topBefore);
  await shot(page, "02-clair");
});
