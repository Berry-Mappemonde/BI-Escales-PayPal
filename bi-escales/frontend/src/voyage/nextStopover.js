/**
 * Prochaine escale sur la route, d’après les milles parcourus (horloge).
 */
export function nextStopover(stops, sailNm) {
  if (!Array.isArray(stops) || !stops.length) return null;
  const nm = Number(sailNm);
  const at = Number.isFinite(nm) ? nm : 0;
  for (const stop of stops) {
    const stopNm = Number(stop.nm ?? stop.cumNm ?? 0);
    if (stopNm >= at - 0.05) return stop;
  }
  return stops[stops.length - 1];
}
