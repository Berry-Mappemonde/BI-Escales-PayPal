import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const root = path.dirname(fileURLToPath(import.meta.url));

// API_PROXY_TARGET=http://127.0.0.1:9 : simuler la CI (aucune API) en local.
const API = process.env.API_PROXY_TARGET || "http://127.0.0.1:8010";
const proxy = {
      "/route": {
        target: API,
        changeOrigin: true,
        bypass(req) {
          // /route.geojson = fichier statique (lien vers backend/data/route.geojson),
          // pas l'API searoute.
          if (req.url?.startsWith("/route.geojson")) return req.url;
        },
      },
      "/proxy": { target: API, changeOrigin: true },
      "/ici": { target: API, changeOrigin: true },
      "/wind": { target: API, changeOrigin: true },
      "/wave": { target: API, changeOrigin: true },
      "/current": { target: API, changeOrigin: true },
      "/weather": { target: API, changeOrigin: true },
      "/api/v1": { target: API, changeOrigin: true },
      "/voyage": { target: API, changeOrigin: true },
      "/escale": { target: API, changeOrigin: true },
      "/logbook": { target: API, changeOrigin: true },
      // Film « Revoir » : ZEE / haute mer du point (server/main.py GET /zee/at).
      "/zee": { target: API, changeOrigin: true },
      // Climatologie BI : par le serveur local (server/bi_proxy.py, cache
      // disque, une requête par cellule par machine), jamais la prod en direct.
      // Incident 2026-09-21 : dev Vite + Playwright → 600-800 req/s
      // sur blueintelligence.online. BI_PROXY_TARGET=https://blueintelligence.online
      // pour retrouver l'ancien direct (le chemin /bi devient alors /api).
      "/bi": process.env.BI_PROXY_TARGET
        ? {
          target: process.env.BI_PROXY_TARGET,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/bi/, "/api"),
        }
        : { target: API, changeOrigin: true },
};

// Poste de recette vu à distance par un tunnel Cloudflare :
// sans ceci, Vite répond 403 « Blocked request ».
// Vite n'ajoute `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` qu'à `server.allowedHosts`
// (et seulement si c'est déjà une liste), jamais à `preview` : la nuit du 22 sept.,
// le tunnel nommé recette.blueintelligence.online a été refusé toute la nuit.
// D'où une liste partagée, qui lit aussi NAVIGUIDE_PREVIEW_HOST (ensure-dev.sh).
const allowedHosts = [
  ".trycloudflare.com",
  ".blueintelligence.online",
  ".naviguide.fr",
  "localhost",
  "127.0.0.1",
  ...(process.env.NAVIGUIDE_PREVIEW_HOST ? [process.env.NAVIGUIDE_PREVIEW_HOST] : []),
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(root, "index.html"),
        lotR8b: path.resolve(root, "lot-r8b.html"),
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5174,
    proxy,
    allowedHosts,
  },
  // `vite preview` (build de prod) parle à la même API : le profil de prod
  // et la fumée Playwright tournent sur une app complète.
  preview: {
    host: "0.0.0.0",
    port: 5174,
    proxy,
    allowedHosts,
  },
});
