/**
 * GEBCO offshore only. No BI map layer.
 * Without a precomputed grid: honest null.
 */
export const COASTAL_CUTOFF_NM = 20;

export function gebcoLookup(lat, lon, { grid = null, distToShoreNm = null } = {}) {
  if (lat == null || lon == null) return null;
  if (distToShoreNm != null && Number(distToShoreNm) < COASTAL_CUTOFF_NM) {
    return null;
  }
  if (!grid || typeof grid.sample !== "function") return null;
  const depth = grid.sample(Number(lat), Number(lon));
  return Number.isFinite(depth) ? depth : null;
}
