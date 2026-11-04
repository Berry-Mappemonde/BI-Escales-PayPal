/** Montant saisi pour une promesse projet (virgule ou point décimal). */
export function normalizeEuroAmountForApi(raw) {
  const text = String(raw ?? "").trim().replace(/\s/g, "").replace(",", ".");
  if (!text) return "";
  return text;
}

export function euroAmountNumeric(raw) {
  const text = normalizeEuroAmountForApi(raw);
  if (!text) return Number.NaN;
  const value = Number(text);
  return Number.isFinite(value) ? value : Number.NaN;
}

/** Minimum 1,00 EUR ; vide ou 0 inclus. */
export function isBelowProjectPledgeMinimum(raw) {
  const value = euroAmountNumeric(raw);
  if (!Number.isFinite(value)) return true;
  return value < 1;
}
