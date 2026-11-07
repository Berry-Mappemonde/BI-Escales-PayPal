// Explicit comparisons are folded by Vite, so disabled builds omit the AG Grid chunk.
export function featureAgGridEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_AG_GRID === "1"
    || import.meta.env.VITE_ENABLE_AG_GRID === "true"
    || import.meta.env.VITE_ENABLE_AG_GRID === "yes"
    || import.meta.env.VITE_ENABLE_AG_GRID === "on";
}

function envFlag(raw: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes(String(raw ?? "0").trim().toLowerCase());
}

/** Off unless explicitly enabled. With it off the Studio module is never imported. */
export function featureAgStudioEnabled(): boolean {
  return envFlag(import.meta.env.VITE_ENABLE_AG_STUDIO);
}

/** AG Grid / AG Studio licence. Empty means the local trial (watermark, no key in the repo). */
export function agGridLicenseKey(): string | undefined {
  const raw = (import.meta.env.VITE_AG_GRID_LICENSE_KEY ?? "").trim();
  return raw.length > 0 ? raw : undefined;
}

/**
 * Optional LLM proxy for the Studio harness. The browser never sends a provider key:
 * the proxy, if any, adds it. Empty keeps the treasurer agent on Studio tools only.
 */
export function agStudioLlmEndpoint(): string | undefined {
  const raw = (import.meta.env.VITE_AG_STUDIO_LLM_ENDPOINT ?? "").trim();
  return raw.length > 0 ? raw : undefined;
}
