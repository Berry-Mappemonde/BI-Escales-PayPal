import { useCallback, useEffect, useState } from "react";
import { getPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { loadTrackedPledgeIds, saveTrackedPledgeIds, trackPledgeId } from "./pledgeQueueStorage";

export function usePledgeQueue() {
  const [ids, setIds] = useState<string[]>(() => loadTrackedPledgeIds());
  const [pledges, setPledges] = useState<PublicPledge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (idList?: string[]) => {
    const list = idList ?? ids;
    if (list.length === 0) {
      setPledges([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.all(
        list.map(async (id) => {
          try {
            return await getPledge(id);
          } catch {
            return null;
          }
        }),
      );
      const found = results.filter((p): p is PublicPledge => p !== null);
      const foundIds = new Set(found.map((p) => p.id));
      const pruned = list.filter((id) => foundIds.has(id));
      if (pruned.length !== list.length) {
        saveTrackedPledgeIds(pruned);
        setIds(pruned);
      }
      setPledges(found);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [ids]);

  const register = useCallback(
    (id: string) => {
      const next = trackPledgeId(id);
      setIds(next);
      void refresh(next);
    },
    [refresh],
  );

  const updatePledge = useCallback((updated: PublicPledge) => {
    setPledges((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  }, []);

  useEffect(() => {
    void refresh(loadTrackedPledgeIds());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chargement initial uniquement
  }, []);

  return { ids, pledges, loading, error, refresh, register, updatePledge, setIds };
}
