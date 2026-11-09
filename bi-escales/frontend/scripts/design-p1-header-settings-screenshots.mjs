/**
 * QA evidence for DESIGN-P1-HEADER-SETTINGS (FR/EN header + settings rail).
 * Usage: npm run dev
 *        node scripts/design-p1-header-settings-screenshots.mjs
 */
import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(here, "../../docs/evidence/design-p1");
const baseUrl = process.env.SCREENSHOT_BASE_URL || "http://127.0.0.1:5173/";

async function waitForShell(page) {
  await page.waitForSelector('[data-testid="ng-shell"]', { timeout: 120_000 });
  await page.waitForSelector('[data-testid="voyage-map"]', { timeout: 120_000 });
}

async function capture(lang, suffix) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript((language) => {
    localStorage.setItem("bi-escales-lang", language);
  }, lang);
  await page.goto(baseUrl);
  await waitForShell(page);
  const langControl = page.getByTestId("ng-settings-controls");
  if (lang === "en") {
    await langControl.getByRole("button", { name: "English" }).click();
  } else {
    await langControl.getByRole("button", { name: "Français" }).click();
  }
  await page.waitForTimeout(500);
  const sidebar = page.getByTestId("ng-sidebar");
  await sidebar.screenshot({
    path: path.join(outDir, `${suffix}-header.png`),
  });
  const tools = page.getByTestId("ng-tools-panel");
  await tools.screenshot({
    path: path.join(outDir, `${suffix}-settings-panel.png`),
  });
  await browser.close();
}

async function main() {
  await capture("fr", "fr");
  await capture("en", "en");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
