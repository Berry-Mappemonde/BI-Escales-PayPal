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

const STOP_PREFIX = "dep-";
const LEG_PREFIX = "leg-";
const LEG_SEPARATOR = "-to-";

/** The part of i18next's `t` the label needs; a component passes its own `t`. */
export type CabinLegTranslate = (key: string, values: { from: string; to: string }) => string;

/**
 * The two stops of a cabin leg, `leg-{from}-to-{to}`, or null when either one is
 * not a stop of the voyage. A stop's own id may contain "-to-", so every split
 * is tried until both sides are known stops.
 */
function cabinLegStops(names: StopNames, id: string): { from: string; to: string } | null {
  if (!id.startsWith(LEG_PREFIX)) return null;
  const legs = id.slice(LEG_PREFIX.length);
  for (let at = legs.indexOf(LEG_SEPARATOR); at !== -1; at = legs.indexOf(LEG_SEPARATOR, at + 1)) {
    const from = names[STOP_PREFIX + legs.slice(0, at)];
    const to = names[STOP_PREFIX + legs.slice(at + LEG_SEPARATOR.length)];
    if (from && to) return { from, to };
  }
  return null;
}

/**
 * What a treasurer reads for a milestone: the stop's name, or for a cabin leg
 * "Cabin: {from} → {to}" (pass `t` to get it in the app's language). An id the
 * voyage does not know (a project, an old stop, a leg with an unknown end) is
 * shown as it is, never hidden.
 */
export function milestoneLabel(
  names: StopNames | null | undefined,
  milestoneId: string | null | undefined,
  t?: CabinLegTranslate,
): string {
  const id = String(milestoneId ?? "").trim();
  if (!id || !names) return id;
  if (names[id]) return names[id];
  const leg = cabinLegStops(names, id);
  if (!leg) return id;
  return t ? t("treasurer.cabinLeg", leg) : `Cabin: ${leg.from} → ${leg.to}`;
}
