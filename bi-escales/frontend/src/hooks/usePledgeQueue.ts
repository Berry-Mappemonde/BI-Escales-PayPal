import { useCallback, useEffect, useState } from "react";
import { getPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { loadTrackedPledgeIds, trackPledgeId } from "./pledgeQueueStorage";

/**
 * La route liste GET /api/escales/pledges n'existe pas.
 * On suit les identifiants en session (pledgeQueueStorage) et on relit
 * GET /api/escales/pledges/{id}. La clé trésorier reste exigée pour afficher la file.
 */
export function usePledgeQueue(adminKey: string) {
  const [pledges, setPledges] = useState<PublicPledge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsKey, setNeedsKey] = useState(true);

  const refresh = useCallback(async () => {
    const key = adminKey.trim();
    if (!key) {
      setNeedsKey(true);
      setError(null);
      setPledges([]);
      return;
    }
    setNeedsKey(false);
    setLoading(true);
    setError(null);
    try {
      const rows: PublicPledge[] = [];
      for (const id of loadTrackedPledgeIds()) {
        rows.push(await getPledge(id));
      }
      setPledges(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  const updatePledge = useCallback((updated: PublicPledge) => {
    trackPledgeId(updated.id);
    setPledges((prev) => {
      const exists = prev.some((pledge) => pledge.id === updated.id);
      if (!exists) return [...prev, updated];
      return prev.map((pledge) => (pledge.id === updated.id ? updated : pledge));
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { pledges, loading, error, needsKey, refresh, updatePledge };
}
