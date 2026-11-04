/** Effectif de la source, pas du cadre. null tant que le catalogue n'a pas répondu. */
export function catalogSourceCount(data) {
  const total = Number(data?.metadata?.total);
  return Number.isFinite(total) ? total : null;
}

/** 0 = la source Capitainerie est vide. Un cadre sans point n'est pas un 0. */
export function isCapitainerieEmpty(count) {
  return count === 0;
}
