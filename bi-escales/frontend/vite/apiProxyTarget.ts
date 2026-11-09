/** Default Vite dev/preview `/api` proxy target when `VITE_API_PROXY_TARGET` is unset. */
export const DEFAULT_API_PROXY_TARGET = "http://localhost:8000";

export function resolveApiProxyTarget(
  env: Record<string, string | undefined> = process.env as Record<string, string | undefined>,
): string {
  const fromEnv = (env.VITE_API_PROXY_TARGET ?? "").trim();
  return fromEnv || DEFAULT_API_PROXY_TARGET;
}

export function buildApiProxy(target: string) {
  return {
    "/api": {
      target,
      changeOrigin: true,
    },
    "/bi-projects.geojson": {
      target,
      changeOrigin: true,
    },
    "/api/escale-marinas.geojson": {
      target,
      changeOrigin: true,
    },
  };
}
