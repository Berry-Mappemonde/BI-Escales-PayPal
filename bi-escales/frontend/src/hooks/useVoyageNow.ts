import { useEffect, useState } from "react";
import { fetchClock } from "../api/escales";

const REFRESH_MS = 30_000;

/** Parse ``GET /api/escales/clock`` into a Date for voyage sampling (not wall clock). */
export function voyageNowFromClock(body: { now?: string; start?: string } | null | undefined): Date | null {
  const iso = String(body?.now || body?.start || "").trim();
  if (!iso) return null;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

/** Keep UI countdown aligned with the API simulated clock (demo pin 2026-11-12 on public hosts). */
export function useVoyageNow(enabled = true): Date | null {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const sync = async () => {
      try {
        const body = await fetchClock();
        const next = voyageNowFromClock(body);
        if (!cancelled && next) setNow(next);
      } catch {
        /* keep last good sample; never fall back to wall clock */
      }
    };

    void sync();
    const id = window.setInterval(() => void sync(), REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled]);

  return now;
}
