/** PayPal zero-decimal presentment currencies (mirrors backend `channel3_paypal.py`). */
export const PAYPAL_ZERO_DECIMAL_CURRENCIES = new Set(["HUF", "JPY", "TWD"]);

export function currencyUsesWholeUnits(currency: string | undefined | null): boolean {
  return PAYPAL_ZERO_DECIMAL_CURRENCIES.has(String(currency || "").trim().toUpperCase());
}

export function formatMinorAsMajor(minor: number | undefined, currency: string, locale: string): string {
  const ccy = String(currency || "EUR").trim().toUpperCase();
  const value = Number(minor);
  if (!Number.isFinite(value)) return "";
  const major = currencyUsesWholeUnits(ccy) ? value : value / 100;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: ccy,
      ...(currencyUsesWholeUnits(ccy) ? { maximumFractionDigits: 0, minimumFractionDigits: 0 } : {}),
    }).format(major);
  } catch {
    return currencyUsesWholeUnits(ccy) ? `${major} ${ccy}` : `${major.toFixed(2)} ${ccy}`;
  }
}

export type WishlistAmountParse = "empty" | "invalid" | "below_min" | "ok";

export function parseWishlistPledgeAmount(
  raw: string,
  currency: string,
): { kind: WishlistAmountParse; apiAmount?: string } {
  const text = String(raw ?? "").trim().replace(/\s/g, "");
  const ccy = String(currency || "EUR").trim().toUpperCase();
  if (!text) return { kind: "empty" };

  if (currencyUsesWholeUnits(ccy)) {
    if (!/^\d+$/.test(text)) return { kind: "invalid" };
    const n = Number(text);
    if (!Number.isFinite(n) || n < 1) return { kind: "below_min" };
    return { kind: "ok", apiAmount: String(Math.trunc(n)) };
  }

  let api = "";
  if (text.includes(",") && text.includes(".")) return { kind: "invalid" };
  if (text.includes(",")) {
    const [whole, frac] = text.split(",");
    if (!/^\d+$/.test(whole) || !/^\d+$/.test(frac) || frac.length === 0 || frac.length > 2) {
      return { kind: "invalid" };
    }
    api = `${whole}.${frac.padEnd(2, "0")}`;
  } else if (text.includes(".")) {
    const [whole, frac] = text.split(".");
    if (!/^\d+$/.test(whole) || !/^\d+$/.test(frac) || frac.length === 0 || frac.length > 2) {
      return { kind: "invalid" };
    }
    api = `${whole}.${frac.padEnd(2, "0")}`;
  } else if (/^\d+$/.test(text)) {
    api = `${text}.00`;
  } else {
    return { kind: "invalid" };
  }
  const numeric = Number(api);
  if (!Number.isFinite(numeric) || numeric < 1) return { kind: "below_min", apiAmount: api };
  return { kind: "ok", apiAmount: api };
}
