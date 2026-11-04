// Recette automatique : fumée + scénarios.
// Port : 5174 par défaut ; `PW_PORT=5199 npm run e2e` quand 5174 est déjà pris.
// `PW_WITH_API=1` démarre l'API hors ligne (stock figé).
import { defineConfig } from "@playwright/test";

const port = Number(process.env.PW_PORT || 5174);
const origin = `http://127.0.0.1:${port}`;
const withApi = process.env.PW_WITH_API === "1";
const apiPort = Number(
  process.env.PW_API_PORT || process.env.NAVIGUIDE_API_PORT || (process.env.PW_PORT ? 8019 : 8010),
);
const apiOrigin = `http://127.0.0.1:${apiPort}`;

const viteServer = {
  // Avec l'API hors ligne, le build est servi avec la route du stock figé (scripts/e2e-preview.sh).
  command: withApi
    ? `bash scripts/e2e-preview.sh ${port}`
    : `npx vite preview --host 127.0.0.1 --port ${port} --strictPort`,
  url: origin,
  reuseExistingServer: !withApi && !process.env.CI && !process.env.PW_PORT,
  timeout: 60_000,
  env: withApi
    ? { ...process.env, API_PROXY_TARGET: apiOrigin }
    : process.env,
};

const apiServer = {
  command: "bash scripts/e2e-store-api.sh",
  url: apiOrigin,
  reuseExistingServer: false,
  timeout: 180_000,
  env: {
    ...process.env,
    NAVIGUIDE_OFFLINE: "1",
    NAVIGUIDE_API_PORT: String(apiPort),
    NAVIGUIDE_OFFICIAL_WORKER: "0",
  },
};

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.js",
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  // Un seul navigateur en CI : le runner a deux cœurs, déjà pris par Vite et l'API.
  workers: process.env.CI ? 1 : 4,
  // 29 oct. : la tranche 1 (fc1, fc2, fl1 ≈ 2,6 min chacun depuis le regel du stock) dépasse 12 min.
  globalTimeout: 15 * 60 * 1000,
  reporter: process.env.CI
    ? [
      ["github"],
      ["list"],
      ["json", { outputFile: "test-results/e2e.json" }],
      ["html", { open: "never" }],
    ]
    : "list",
  use: {
    baseURL: origin,
    // Les scénarios existants affirment le français. Le visiteur sans choix est couvert par ouverture-langue.
    storageState: "./e2e/.auth/fr.json",
    headless: true,
    viewport: { width: 1280, height: 800 },
    trace: process.env.CI ? "off" : "retain-on-failure",
    navigationTimeout: 20_000,
    launchOptions: process.env.PW_RELAXED_BROWSER === "1"
      ? { args: ["--no-sandbox", "--disable-gpu", "--single-process", "--no-zygote"] }
      : undefined,
  },
  webServer: withApi ? [viteServer, apiServer] : [viteServer],
});
