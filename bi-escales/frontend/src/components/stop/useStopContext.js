import { useCallback, useEffect, useState } from "react";
import { fetchClock, fetchFund, listMilestones } from "../../api/escales";

const EMPTY = { now: null, milestones: null, fund: null };

const value = (result) => (result.status === "fulfilled" ? result.value : null);

/**
 * The clock, the milestones and this stop's public fund. Each is null if its
 * call failed, and the panel drops whatever depended on it. No admin key is
 * sent, so this is what any visitor can see.
 */
export function useStopContext(milestoneId) {
  const [loaded, setLoaded] = useState({ id: "", ...EMPTY });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!milestoneId) return undefined;
    let cancel = false;
    void Promise.allSettled([fetchClock(), listMilestones(), fetchFund(milestoneId)]).then(
      ([clock, milestones, fund]) => {
        if (cancel) return;
        const list = value(milestones);
        setLoaded({
          id: milestoneId,
          now: value(clock)?.now ?? null,
          milestones: Array.isArray(list) ? list : null,
          fund: value(fund),
        });
      },
    );
    return () => {
      cancel = true;
    };
  }, [milestoneId, generation]);

  const refresh = useCallback(() => setGeneration((count) => count + 1), []);

  // A switch of stop shows nothing until its own answers arrive, never the last stop's.
  return { ...(loaded.id === milestoneId ? loaded : EMPTY), refresh };
}
