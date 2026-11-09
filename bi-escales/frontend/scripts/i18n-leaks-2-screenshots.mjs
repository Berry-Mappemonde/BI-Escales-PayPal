/**
 * QA evidence for I18N-LEAKS-2 (FR treasurer studio, EN gear tab).
 * Usage: VITE_ENABLE_AG_STUDIO=1 VITE_API_PROXY_TARGET=https://bi-escales-api-test2.onrender.com npm run dev
 *        node scripts/i18n-leaks-2-screenshots.mjs
 */
import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(here, "../../docs/evidence/i18n-leaks-2");
const baseUrl = process.env.SCREENSHOT_BASE_URL || "http://127.0.0.1:5173/";

async function waitForMap(page) {
  await page.waitForSelector('[data-testid="voyage-map"]', { timeout: 120_000 });
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.addInitScript(() => {
    localStorage.setItem("bi-escales-lang", "fr");
  });
  await page.goto(baseUrl);
  await waitForMap(page);

  const expandTools = page.getByTestId("tools-expand");
  if (await expandTools.isVisible().catch(() => false)) {
    await expandTools.click();
  }
  const demoTreasurer = page.getByTestId("demo-treasurer-button");
  if (await demoTreasurer.isVisible({ timeout: 15_000 }).catch(() => false)) {
    await demoTreasurer.click();
  }
  const treasurerToggle = page.getByTestId("treasurer-panel-toggle");
  if (await treasurerToggle.isVisible().catch(() => false)) {
    await treasurerToggle.click();
  }

  const studioOpen = page.getByTestId("treasurer-studio-open");
  if (await studioOpen.isVisible({ timeout: 30_000 }).catch(() => false)) {
    await studioOpen.click();
    await page.waitForSelector('[data-testid="treasurer-ag-studio"]', { timeout: 60_000 });
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: path.join(outDir, "fr-treasurer-ag-studio-dashboard.png"),
      fullPage: true,
    });
    await page.getByTestId("treasurer-studio-close").click().catch(() => {});
  }

  await page.evaluate(() => {
    localStorage.setItem("bi-escales-lang", "en");
    window.dispatchEvent(new Event("storage"));
  });
  await page.getByLabel("English").click();
  await page.getByRole("tab", { name: "Gear" }).click();
  await page.waitForSelector('[data-testid="gear-list"]', { timeout: 30_000 });
  await page.getByTestId("gear-list").locator("summary").click();
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: path.join(outDir, "en-gear-tab.png"),
    fullPage: true,
  });

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
