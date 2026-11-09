/**
 * PayPal-supported presentment currencies (sandbox subset documented in C3-APP PR).
 * Prefer backend `funding_supported` when present; this list is the frontend fallback only.
 * @see https://developer.paypal.com/api/rest/reference/currency-codes/
 */
export const PAYPAL_SUPPORTED_CURRENCY_CODES = new Set([
  "AUD",
  "BRL",
  "CAD",
  "CHF",
  "CZK",
  "DKK",
  "EUR",
  "GBP",
  "HKD",
  "HUF",
  "ILS",
  "JPY",
  "MXN",
  "NOK",
  "NZD",
  "PHP",
  "PLN",
  "SEK",
  "SGD",
  "THB",
  "TWD",
  "USD",
]);

export function isPayPalSupportedCurrency(code: string | undefined | null): boolean {
  const ccy = String(code || "").trim().toUpperCase();
  return Boolean(ccy) && PAYPAL_SUPPORTED_CURRENCY_CODES.has(ccy);
}
