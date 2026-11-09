import type { Channel3CatalogItem } from "../api/types";
import { formatMinorAsMajor } from "./channel3Money";
import { unitPriceFields } from "./wishlistLine";

/** Display native unit price from API (never invent FX or multiply by qty). */
export function formatNativePrice(item: Channel3CatalogItem, locale: string): string {
  const unit = unitPriceFields(item);
  const currency = String(unit.price_currency || item.target_currency || "").trim().toUpperCase() || "EUR";
  const display = String(unit.price_display || "").trim();
  if (display) {
    const minor = Number(unit.price_amount_minor);
    if (Number.isFinite(minor)) {
      return formatMinorAsMajor(minor, currency, locale);
    }
    return `${display} ${currency}`;
  }
  const minor = Number(unit.price_amount_minor);
  if (Number.isFinite(minor)) {
    return formatMinorAsMajor(minor, currency, locale);
  }
  return currency;
}

/** Use API `funded_pct` only (computed server-side in native currency). */
export function fundingPct(item: Channel3CatalogItem): number | null {
  if (item.funded_pct == null) return null;
  const n = Number(item.funded_pct);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null;
}

export function formatMinorMoney(
  minor: number | undefined,
  currency: string | undefined,
  locale: string,
): string {
  return formatMinorAsMajor(minor, String(currency || "EUR"), locale);
}
