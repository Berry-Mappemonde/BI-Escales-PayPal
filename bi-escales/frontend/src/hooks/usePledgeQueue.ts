import { useCallback, useEffect, useState } from "react";
import { listPledges } from "../api/escales";
import type { PublicPledge } from "../api/types";

/**
 * La file vient de GET /api/escales/pledges. La clé trésorier est exigée.
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
      setPledges(await listPledges(key));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  const updatePledge = useCallback((updated: PublicPledge) => {
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
