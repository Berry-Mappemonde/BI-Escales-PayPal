import { useEffect, useRef } from "react";

/**
 * When `state` changes, the button that was pressed is usually gone, so focus
 * moves to the first enabled button in the region, or to the region itself if
 * none is left, instead of falling back to the body. A change that arrives on
 * its own, like a countdown ending, leaves focus alone if it has moved elsewhere.
 */
export function useFocusFirstButton<T extends HTMLElement>(state: unknown) {
  const regionRef = useRef<T>(null);
  const previous = useRef(state);

  useEffect(() => {
    if (previous.current === state) return;
    previous.current = state;
    const region = regionRef.current;
    const active = document.activeElement;
    if (active && active !== document.body && !region?.contains(active)) return;
    (region?.querySelector<HTMLElement>("button:not(:disabled)") ?? region)?.focus();
  }, [state]);

  return regionRef;
}
