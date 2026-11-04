import { useCallback, useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "";
export const JOURNAL_REFRESH_MS = 5 * 60_000;

/**
 * Journal de bord du voyage officiel (lecture seule, public).
 * Rafraîchi toutes les 5 min : le serveur n'écrit que 4 positions par jour.
 */
export function useOfficialJournal({ enabled, limit = 60 } = {}) {
  const [journal, setJournal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const aliveRef = useRef(true);

  const refresh = useCallback(async () => {
    if (!enabled) return null;
    setLoading(true);
    try {
      const res = await fetch(`${API}/voyage/official/journal?limit=${encodeURIComponent(limit)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (aliveRef.current) {
        setJournal(data);
        setError(null);
      }
      return data;
    } catch (err) {
      if (aliveRef.current) setError(err?.message || "journal");
      return null;
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, [enabled, limit]);

  useEffect(() => {
    aliveRef.current = true;
    if (!enabled) return undefined;
    refresh();
    const id = setInterval(refresh, JOURNAL_REFRESH_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
  }, [enabled, refresh]);

  return { journal, loading, error, refresh };
}
