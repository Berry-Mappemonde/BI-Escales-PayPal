import type { Channel3CatalogItem } from "../api/types";
import { unitPriceFields } from "./wishlistLine";

/** Display native unit price from API money fields (never invent FX or multiply by qty). */
export function formatNativePrice(item: Channel3CatalogItem, locale: string): string {
  const unit = unitPriceFields(item);
  const currency = String(unit.price_currency || item.target_currency || "").trim() || "EUR";
  const display = String(unit.price_display || "").trim();
  if (display) {
    try {
      const numeric = Number(display.replace(",", "."));
      if (Number.isFinite(numeric)) {
        return new Intl.NumberFormat(locale, { style: "currency", currency }).format(numeric);
      }
    } catch {
      /* fall through */
    }
    return `${display} ${currency}`;
  }
  const minor = Number(unit.price_amount_minor);
  if (Number.isFinite(minor)) {
    return new Intl.NumberFormat(locale, { style: "currency", currency }).format(minor / 100);
  }
  return currency;
}

function parseMajorDisplay(value: string | undefined): number | null {
  const text = String(value || "").trim().replace(",", ".");
  if (!text) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/** Bar width from API fields only (no FX, no price×qty). */
export function fundingPct(item: Channel3CatalogItem): number | null {
  if (item.funded_pct != null) {
    const n = Number(item.funded_pct);
    return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null;
  }
  const target = parseMajorDisplay(item.target_display);
  const funded = parseMajorDisplay(item.funded_display);
  if (target != null && target > 0 && funded != null) {
    return Math.max(0, Math.min(100, Math.round((funded / target) * 100)));
  }
  if (Number(item.target_amount_minor) > 0) {
    return 0;
  }
  return null;
}

export function formatMinorMoney(
  minor: number | undefined,
  currency: string | undefined,
  locale: string,
): string {
  const ccy = String(currency || "EUR").trim().toUpperCase();
  const value = Number(minor);
  if (!Number.isFinite(value)) return "";
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency: ccy }).format(value / 100);
  } catch {
    return `${(value / 100).toFixed(2)} ${ccy}`;
  }
}
