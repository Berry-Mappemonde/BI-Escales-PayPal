import i18n from "../i18n";

/** App languages. Anything other than English stays on the French copy. */
export function studioLanguage(language?: string): "fr" | "en" {
  const value = (language ?? i18n.resolvedLanguage ?? i18n.language ?? "fr").toLowerCase();
  return value.startsWith("en") ? "en" : "fr";
}

export function studioT(language?: string) {
  const lng = studioLanguage(language);
  return (key: string, options?: Record<string, unknown>) => String(i18n.t(key, { ...options, lng }));
}

/** FR `120,00 €`, EN `120.00 EUR`. No thousands separator, always two decimals. */
export function formatPledgeAmount(value: number, language?: string): string {
  const safe = Number.isFinite(value) ? value : 0;
  const [whole, frac] = safe.toFixed(2).split(".");
  if (studioLanguage(language) === "en") return `${whole}.${frac} EUR`;
  return `${whole},${frac} €`;
}

const STATUS_KEYS: Record<string, string> = {
  created: "studio.statusCreated",
  authorized: "studio.held",
  vaulted: "studio.saved",
  pending: "studio.statusPending",
  captured: "studio.captured",
  partially_refunded: "studio.statusPartiallyRefunded",
  refunded: "studio.statusRefunded",
  voided: "studio.released",
  capture_failed: "studio.statusCaptureFailed",
  charge_failed: "studio.statusChargeFailed",
  token_delete_pending: "studio.statusTokenDeletePending",
  settled: "studio.statusSettled",
  failed: "studio.statusFailed",
};

export function formatPledgeStatus(status: string, language?: string): string {
  const key = STATUS_KEYS[status];
  return key ? studioT(language)(key) : status;
}
