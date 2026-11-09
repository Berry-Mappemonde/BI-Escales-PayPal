/** Below 768px the left sidebar covers the stop panel. */
const NARROW_QUERY = "(max-width: 767.98px)";

/** Bottom sheet for the pledge / settings rail (unchanged from 1024px desktop). */
const MOBILE_SHEET_QUERY = "(max-width: 900px)";

function matchesMedia(query: string): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

/** Read when it is needed, not once, so a rotated phone gets the right answer. */
export function isNarrowScreen(): boolean {
  return matchesMedia(NARROW_QUERY);
}

/** True when the right rail is docked as a bottom sheet instead of a side column. */
export function isMobileToolsSheet(): boolean {
  return matchesMedia(MOBILE_SHEET_QUERY);
}
