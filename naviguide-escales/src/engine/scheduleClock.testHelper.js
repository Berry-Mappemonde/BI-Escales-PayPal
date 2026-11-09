/** Test-only anchors (departure 2026-11-12). */

export const VOYAGE_DEPARTURE_ISO = "2026-11-12T08:00:00.000Z";

export function departurePlusDays(days, hourUtc = 8) {
  const base = new Date(VOYAGE_DEPARTURE_ISO);
  base.setUTCDate(base.getUTCDate() + days);
  base.setUTCHours(hourUtc, 0, 0, 0);
  return base.toISOString().replace(".000Z", "Z");
}
