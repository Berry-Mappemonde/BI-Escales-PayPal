import { useEffect, useRef } from "react";

/**
 * When `state` changes, the button that was pressed is usually gone, so focus
 * moves to the first button in the region, or to the region itself if none is
 * left, instead of falling back to the body.
 */
export function useFocusFirstButton<T extends HTMLElement>(state: unknown) {
  const regionRef = useRef<T>(null);
  const previous = useRef(state);

  useEffect(() => {
    if (previous.current === state) return;
    previous.current = state;
    const region = regionRef.current;
    (region?.querySelector("button") ?? region)?.focus();
  }, [state]);

  return regionRef;
}
