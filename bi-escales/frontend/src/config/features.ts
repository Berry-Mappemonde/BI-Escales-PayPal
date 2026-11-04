export function featureAgGridEnabled(): boolean {
  const raw = import.meta.env.VITE_ENABLE_AG_GRID ?? "0";
  return ["1", "true", "yes", "on"].includes(String(raw).trim().toLowerCase());
}

export function paypalClientId(): string {
  return (import.meta.env.VITE_PAYPAL_CLIENT_ID ?? "").trim();
}

export function apiBase(): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").trim();
  return base.replace(/\/$/, "");
}
