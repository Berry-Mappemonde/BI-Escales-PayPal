import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { bryntumFallback } from "./vite/bryntumFallback.mjs";
import { buildApiProxy, resolveApiProxyTarget } from "./vite/apiProxyTarget";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxy = buildApiProxy(resolveApiProxyTarget(env));

  return {
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
  };
});
