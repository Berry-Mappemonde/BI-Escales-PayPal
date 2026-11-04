import { useCallback, useEffect, useRef, useState } from "react";
import { fetchWeatherComposite, satelliteBusy, weatherPollMs } from "./weatherSnapshot.js";

const API_URL = import.meta.env.VITE_API_URL ?? "";

/**
 * The satellite / weather popup of a route click (moved out of App.jsx,
 * behaviour unchanged). One composite request at a time (the previous one is
 * aborted), then a gentle poll while the shared weather pipeline is pending.
 * `open(lat, lon, extra)` shows the popup and fetches; `close()` aborts and hides.
 */
export function useSatellitePopup() {
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("wind");
  const requestRef = useRef({ id: 0, controller: null });

  const cancel = useCallback(() => {
    requestRef.current.id += 1;
    requestRef.current.controller?.abort();
    requestRef.current.controller = null;
  }, []);

  const close = useCallback(() => {
    cancel();
    setSelected(null);
    setLoading(false);
  }, [cancel]);

  const open = useCallback(async (lat, lon, extra = {}) => {
    const previous = requestRef.current;
    previous.controller?.abort();
    const controller = new AbortController();
    const id = previous.id + 1;
    requestRef.current = { id, controller };
    setLoading(true);
    setTab("wind");
    setSelected({ lat, lon, ...extra });
    try {
      const data = await fetchWeatherComposite(lat, lon, { signal: controller.signal, api: API_URL });
      if (requestRef.current.id !== id) return;
      setSelected((prev) => (prev ? { ...prev, ...data } : prev));
      setLoading(satelliteBusy(data));
    } catch {
      if (controller.signal.aborted || requestRef.current.id !== id) return;
      setSelected((prev) => (prev ? { ...prev, error: true } : prev));
      setLoading(false);
    } finally {
      if (requestRef.current.id === id) requestRef.current.controller = null;
    }
  }, []);

  // Poll while the weather is still being assembled server-side.
  useEffect(() => {
    if (!selected || selected.error) return undefined;
    const { lat, lon } = selected;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return undefined;
    const requestId = requestRef.current.id;
    const delay = weatherPollMs(selected);
    const timer = setInterval(() => {
      const controller = new AbortController();
      requestRef.current.controller?.abort();
      requestRef.current.controller = controller;
      fetchWeatherComposite(lat, lon, { signal: controller.signal, api: API_URL })
        .then((data) => {
          if (requestRef.current.id !== requestId) return;
          setSelected((prev) => (prev && prev.lat === lat && prev.lon === lon ? { ...prev, ...data } : prev));
          setLoading(satelliteBusy(data));
        })
        .catch(() => {});
    }, delay);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.lat, selected?.lon, selected?.status, selected?.refreshing, selected?.error]);

  useEffect(() => cancel, [cancel]);

  return { selected, setSelected, loading, tab, setTab, open, close, cancel };
}
