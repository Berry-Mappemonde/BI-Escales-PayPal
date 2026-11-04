function envFlag(raw: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes(String(raw ?? "0").trim().toLowerCase());
}

export function featureAgGridEnabled(): boolean {
  return envFlag(import.meta.env.VITE_ENABLE_AG_GRID);
}

/** Lot L3b. Off unless explicitly enabled, so removing AG Studio leaves the app unchanged. */
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

export function paypalClientId(): string {
  return (import.meta.env.VITE_PAYPAL_CLIENT_ID ?? "").trim();
}

export function apiBase(): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").trim();
  return base.replace(/\/$/, "");
}
