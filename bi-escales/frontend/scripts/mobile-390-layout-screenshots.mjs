/**
 * QA evidence for MOBILE-390-LAYOUT (390×844 bottom sheet + desktop regression).
 * Usage: npm run build && npm run preview -- --host 127.0.0.1 --port 4173
 *        SCREENSHOT_BASE_URL=http://127.0.0.1:4173/ node scripts/mobile-390-layout-screenshots.mjs
 */
import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(here, "../../docs/screenshots/mobile-390");
const baseUrl = process.env.SCREENSHOT_BASE_URL || "http://127.0.0.1:4173/";

async function waitForShell(page) {
  await page.waitForSelector('[data-testid="ng-shell"]', { timeout: 120_000 });
  await page.waitForSelector('[data-testid="voyage-map"]', { timeout: 120_000 });
}

async function captureMobile(lang) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.addInitScript((language) => {
    localStorage.setItem("bi-escales-lang", language);
  }, lang);
  await page.goto(baseUrl);
  await waitForShell(page);
  await page.getByTestId("ng-sidebar-toggle").click();
  await page.waitForTimeout(300);
  await page.screenshot({
    path: path.join(outDir, `mobile-390-${lang}-sheet-open.png`),
    fullPage: false,
  });
  await page.getByTestId("ng-tools-toggle").click();
  await page.waitForTimeout(300);
  await page.screenshot({
    path: path.join(outDir, `mobile-390-${lang}-sheet-collapsed.png`),
    fullPage: false,
  });
  await browser.close();
}

async function captureDesktop() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(baseUrl);
  await waitForShell(page);
  await page.screenshot({
    path: path.join(outDir, "desktop-1440-layout.png"),
    fullPage: false,
  });
  await browser.close();
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  await captureMobile("fr");
  await captureMobile("en");
  await captureDesktop();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
