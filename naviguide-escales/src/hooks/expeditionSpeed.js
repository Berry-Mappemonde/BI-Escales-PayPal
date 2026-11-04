/**
 * En Suivre, la vitesse affichée est celle de l'horloge (0 à quai).
 * Aucune polaire × GRIB concurrente.
 */
export function resolveFollowSpeed(clockSample) {
  const regime = clockSample?.regime || clockSample?.kind || null;
  if (!clockSample) return { knots: null, kind: null, live: false };
  if (clockSample.atQuay) return { knots: 0, kind: regime, live: false };
  const raw = Number(clockSample.speedKnots);
  return {
    knots: Number.isFinite(raw) ? raw : null,
    kind: regime,
    live: false,
  };
}
