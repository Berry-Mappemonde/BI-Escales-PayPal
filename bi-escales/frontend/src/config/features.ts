function envFlag(raw: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes(String(raw ?? "0").trim().toLowerCase());
}

export function featureAgGridEnabled(): boolean {
  return envFlag(import.meta.env.VITE_ENABLE_AG_GRID);
}

/** Off unless explicitly enabled. The hackathon build keeps the Studio trial watermark. */
export function featureAgStudioEnabled(): boolean {
  return envFlag(import.meta.env.VITE_ENABLE_AG_STUDIO);
}

export function agGridLicenseKey(): string | undefined {
  const raw = (import.meta.env.VITE_AG_GRID_LICENSE_KEY ?? "").trim();
  return raw.length > 0 ? raw : undefined;
}

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
