import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  reporter: "list",
  outputDir: "/tmp/bi-escales-wallet-e2e",
  use: {
    baseURL: "http://127.0.0.1:5178",
    headless: true,
    trace: "off",
    screenshot: "off",
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || "/usr/bin/chromium" },
  },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 5178 --strictPort", url: "http://127.0.0.1:5178", reuseExistingServer: false },
});
