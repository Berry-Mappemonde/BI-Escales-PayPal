/** Below 768px the left sidebar covers the stop panel. */
const NARROW_QUERY = "(max-width: 767.98px)";

/** Read when it is needed, not once, so a rotated phone gets the right answer. */
export function isNarrowScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW_QUERY).matches;
}
