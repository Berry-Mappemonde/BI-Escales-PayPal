import { useCallback, useEffect, useState } from "react";
import { listPledges } from "../api/escales";
import type { PublicPledge } from "../api/types";

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
      const rows = await listPledges(key);
      setPledges(rows);
    } catch (e) {
      // A failed fetch must not drop pledges that were already loaded.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  const updatePledge = useCallback((updated: PublicPledge) => {
    setPledges((prev) => {
      const exists = prev.some((p) => p.id === updated.id);
      if (!exists) return [...prev, updated];
      return prev.map((p) => (p.id === updated.id ? updated : p));
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { pledges, loading, error, needsKey, refresh, updatePledge };
}
