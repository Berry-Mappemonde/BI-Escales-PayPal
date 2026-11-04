import { useEffect, useState } from "react";
import { FILM_ZEE_STEP_DEG, filmZeeBucket, filmZeeForBucket } from "../engine/filmZeeStep.js";

export { FILM_ZEE_STEP_DEG, filmZeeBucket, filmZeeForBucket };

const API_URL = import.meta.env?.VITE_API_URL ?? "";

/**
 * EEZ at the replayed position, refreshed when the film boat changes bucket.
 * GET /zee/at is local polygons only. A missing or stale answer stays null
 * (unknown), never the previous zone and never a high-seas claim.
 */
export function useFilmZee({ enabled = false, lat = null, lon = null } = {}) {
  const [zee, setZee] = useState(null);
  const bucket = enabled ? filmZeeBucket(lat, lon) : "";

  useEffect(() => {
    if (!bucket) {
      setZee(null);
      return undefined;
    }
    // Drop the previous step before the new lookup lands. A failed
    // request leaves null, not Adelaide or « high seas » from earlier.
    setZee(null);
    const [la, lo] = bucket.split(":").map(Number);
    const ctrl = new AbortController();
    let cancelled = false;
    fetch(`${API_URL}/zee/at?lat=${encodeURIComponent(la)}&lon=${encodeURIComponent(lo)}`, {
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data || typeof data !== "object") return;
        setZee({ ...data, bucket });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [bucket]);

  return filmZeeForBucket(zee, bucket);
}
