/** Stop names by milestone id, from the voyage stops the app has already loaded. */
export type StopNames = Record<string, string>;

export function stopNamesFromStops(
  stops: ReadonlyArray<{ milestoneId?: string | null; name?: string | null }> | null | undefined,
): StopNames {
  const names: StopNames = {};
  for (const stop of stops ?? []) {
    const id = String(stop?.milestoneId ?? "").trim();
    const name = String(stop?.name ?? "").trim();
    // A stop the route lists twice keeps its first name.
    if (id && name && !(id in names)) names[id] = name;
  }
  return names;
}

/**
 * What a treasurer reads for a milestone: the stop's name. An id the voyage does
 * not know (a cabin leg, a project, an old stop) is shown as it is, never hidden.
 */
export function milestoneLabel(names: StopNames | null | undefined, milestoneId: string | null | undefined): string {
  const id = String(milestoneId ?? "").trim();
  return (id && names?.[id]) || id;
}
