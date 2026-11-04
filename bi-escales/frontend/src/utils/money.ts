/** French: ``120,00 €``. English: ``120.00 EUR``. */
export function formatMoney(amount: string | number, language: string): string {
  const value = typeof amount === "number" ? amount : Number.parseFloat(amount);
  if (!Number.isFinite(value)) return String(amount);
  const fixed = value.toFixed(2);
  if (language.toLowerCase().startsWith("en")) return `${fixed} EUR`;
  return `${fixed.replace(".", ",")} €`;
}
