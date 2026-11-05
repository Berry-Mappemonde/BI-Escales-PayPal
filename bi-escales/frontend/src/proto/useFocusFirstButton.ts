import { useEffect, useRef } from "react";

/**
 * When `state` changes, the button that was pressed is usually gone, so focus
 * moves to the first button in the region instead of falling back to the body.
 */
export function useFocusFirstButton<T extends HTMLElement>(state: unknown) {
  const regionRef = useRef<T>(null);
  const previous = useRef(state);

  useEffect(() => {
    if (previous.current === state) return;
    previous.current = state;
    regionRef.current?.querySelector("button")?.focus();
  }, [state]);

  return regionRef;
}
