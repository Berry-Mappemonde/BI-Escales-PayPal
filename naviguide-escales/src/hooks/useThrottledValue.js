import { useEffect, useRef, useState } from "react";

/**
 * Publie une valeur vers le HUD à cadence bornée, sans ralentir le calcul
 * impératif qui continue de s'exécuter entre deux publications.
 */
export function useThrottledValue(value, delayMs) {
  const [throttled, setThrottled] = useState(value);
  const latestRef = useRef(value);
  const lastCommitRef = useRef(0);

  useEffect(() => {
    latestRef.current = value;
    const now = performance.now();
    const wait = Math.max(0, lastCommitRef.current + delayMs - now);
    const commit = () => {
      lastCommitRef.current = performance.now();
      setThrottled(latestRef.current);
    };
    if (wait === 0) {
      commit();
      return undefined;
    }
    const timer = window.setTimeout(commit, wait);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return throttled;
}
