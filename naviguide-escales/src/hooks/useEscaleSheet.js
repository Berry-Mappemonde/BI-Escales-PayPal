import { useEffect, useRef, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL ?? "";

/**
 * The escale sheet: GET /escale for the selected stop, one request
 * per (name, position, lang), kept in this tab. `stop` = { name, lat, lon }
 * or null. Never blocks Play; a failure is a sheet with an error, not a crash.
 */
export function useEscaleSheet(stop, lang = "fr") {
  const [state, setState] = useState({ key: null, fiche: null, loading: false, error: null });
  const cacheRef = useRef(new Map());

  const key = stop && Number.isFinite(stop.lat) && Number.isFinite(stop.lon) && stop.name
    ? `${stop.name}|${stop.lat.toFixed(2)}|${stop.lon.toFixed(2)}|${lang}`
    : null;

  useEffect(() => {
    if (!key) {
      setState({ key: null, fiche: null, loading: false, error: null });
      return undefined;
    }
    const cached = cacheRef.current.get(key);
    if (cached) {
      setState({ key, fiche: cached, loading: false, error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ key, fiche: null, loading: true, error: null });
    const url = `${API_URL}/escale?name=${encodeURIComponent(stop.name)}&lat=${stop.lat}&lon=${stop.lon}&lang=${encodeURIComponent(lang)}`;
    fetch(url, { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((fiche) => {
        cacheRef.current.set(key, fiche);
        setState({ key, fiche, loading: false, error: null });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState({ key, fiche: null, loading: false, error: err?.message || "error" });
      });
    return () => controller.abort();
  }, [key, lang, stop?.name, stop?.lat, stop?.lon]);

  return state;
}
