/** True when the API returned HTTP 429 for captain chat or review. */
export function isCaptainRateLimitMessage(message: string): boolean {
  const text = String(message || "").trim();
  if (!text) return false;
  return /too many requests/i.test(text) || /trop de requ[eê]tes/i.test(text);
}
