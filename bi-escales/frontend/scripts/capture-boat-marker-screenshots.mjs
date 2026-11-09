import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "../docs/boat-marker-card");
const baseUrl = process.env.PREVIEW_URL || "http://127.0.0.1:4173";

async function capture(lang) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.evaluate((lng) => {
    localStorage.setItem("bi-escales-lang", lng);
  }, lang);
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="voyage-map"]', { timeout: 60_000 });
  await page.waitForTimeout(2000);
  const boatChip = page.getByTestId("captain-locate-boat");
  await boatChip.click();
  await page.waitForSelector('[data-testid="escale-popup"]', { timeout: 30_000 });
  await page.screenshot({
    path: join(outDir, `after-${lang}-boat-card.png`),
    fullPage: false,
  });
  await browser.close();
}

await mkdir(outDir, { recursive: true });
await capture("fr");
await capture("en");
