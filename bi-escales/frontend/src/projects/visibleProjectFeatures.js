/** Liste affichée : inclut le projet sélectionné (carte) même hors top 100 ou filtre. */
export function visibleProjectFeatures(allFeatures, filtered, selectedProjectId, cap = 100) {
  const list = filtered.slice(0, cap);
  if (!selectedProjectId) return list;
  const pinned = (allFeatures || []).find((feature) => feature.properties?.id === selectedProjectId);
  if (!pinned) return list;
  if (list.some((feature) => feature.properties?.id === selectedProjectId)) return list;
  const rest = list.filter((feature) => feature.properties?.id !== selectedProjectId);
  return [pinned, ...rest.slice(0, Math.max(0, cap - 1))];
}
