import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { bryntumFallback } from "./vite/bryntumFallback.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "https://bi-escales-api.onrender.com";
const apiProxy = {
  "/api": {
    target: apiProxyTarget,
    changeOrigin: true,
  },
  "/bi-projects.geojson": {
    target: apiProxyTarget,
    changeOrigin: true,
  },
  "/api/escale-marinas.geojson": {
    target: apiProxyTarget,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [bryntumFallback(), react()],
  server: {
    port: 5173,
    fs: { allow: [repoRoot] },
    proxy: apiProxy,
  },
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
});
