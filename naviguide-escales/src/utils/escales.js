/**
 * If `toIdx` points at an intermediate (no flag), advance until
 * la prochaine escale obligatoire. Sinon laisse l'index tel quel.
 */
export function nextEscaleIndex(stops, toIdx) {
  if (!Array.isArray(stops) || !stops.length) return toIdx;
  const start = Math.max(0, Math.min(toIdx ?? 0, stops.length - 1));
  if (stops[start]?.flag) return start;
  for (let i = start + 1; i < stops.length; i++) {
    if (stops[i].flag) return i;
  }
  return start;
}

export function nextEscaleStop(stops, toIdx) {
  const index = nextEscaleIndex(stops, toIdx);
  return { index, stop: stops?.[index] ?? null };
}

/**
 * Une escale déjà vue (Cayenne réinsérée) ne compte pas deux fois.
 * Le dernier point qui reprend un nom déjà vu (retour à La Rochelle) est gardé.
 */
export function dropRepeatedStops(marks) {
  const named = (marks || []).filter((mark) => mark?.name);
  if (named.length <= 1) return named;
  const seen = new Set();
  const out = [];
  for (let i = 0; i < named.length; i++) {
    const name = named[i].name;
    const isLast = i === named.length - 1;
    if (seen.has(name) && !isLast) continue;
    seen.add(name);
    out.push(named[i]);
  }
  return out;
}
