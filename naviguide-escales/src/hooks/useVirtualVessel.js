import { createElement, useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "naviguide_sim_voyage_v1";
const API = import.meta.env.VITE_API_URL ?? "";

function readStored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    return null;
  }
}

function writeStored(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch { /* quota */ }
}

function fingerprint(points, t0, startAt) {
  const first = points?.[0];
  const last = points?.[points.length - 1];
  return `${t0}|${startAt}|${points?.length}|${first?.lat}|${last?.lat}|${last?.cumNm}`;
}

/** Repli progressif après un POST /voyage en échec : 2 s → 30 s, jamais un martelage. */
export const CREATE_BACKOFF_MS = [2000, 4000, 8000, 16000, 30000];

export function createBackoffMs(failCount) {
  const n = Number(failCount);
  if (!Number.isFinite(n) || n <= 0) return 0;
  const i = Math.min(CREATE_BACKOFF_MS.length, Math.floor(n)) - 1;
  return CREATE_BACKOFF_MS[i];
}

/** GET /voyage/{id}/at seulement quand l'horloge a des sommets. */
export function shouldFetchAt(clock) {
  if (!clock || typeof clock !== "object") return false;
  if (clock.status === "preparing") return false;
  return Array.isArray(clock.vertices) && clock.vertices.length > 0;
}

export function useVirtualVessel({
  enabled,
  forecast,
  follow,
  t0,
  startAt,
  expeditionId,
  routeKind,
  points,
  marks,
}) {
  const [voyage, setVoyage] = useState(null);
  const [live, setLive] = useState(null);
  const [clock, setClock] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const fpRef = useRef("");
  const creatingRef = useRef(false);
  const failCountRef = useRef(0);
  const nextCreateAtRef = useRef(0);
  const lastAttemptFpRef = useRef("");
  const retryTimerRef = useRef(null);
  const clockRef = useRef(null);

  const persist = useCallback((voy) => {
    if (!voy) return;
    writeStored({
      voyageId: voy.voyageId,
      t0: voy.t0,
      expedition_id: voy.expedition_id,
      routeKind: voy.routeKind,
      routeRev: voy.routeRev,
      follow: Boolean(follow),
      forecastStatus: voy.forecastStatus,
    });
  }, [follow]);

  const fetchJson = useCallback(async (path, opts) => {
    const res = await fetch(`${API}${path}`, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }, []);

  const refreshLive = useCallback(async (voyageId, clockHint) => {
    if (!voyageId) return null;
    const ck = clockHint !== undefined ? clockHint : clockRef.current;
    if (!shouldFetchAt(ck)) return null;
    const sample = await fetchJson(`/voyage/${voyageId}/at`);
    setLive(sample);
    return sample;
  }, [fetchJson]);

  const refreshMeta = useCallback(async (voyageId) => {
    const meta = await fetchJson(`/voyage/${voyageId}`);
    setVoyage(meta);
    persist(meta);
    try {
      const ck = await fetchJson(`/voyage/${voyageId}/clock`);
      clockRef.current = ck;
      setClock(ck);
      if (shouldFetchAt(ck)) {
        await refreshLive(voyageId, ck);
      }
    } catch { /* clock optional */ }
    return meta;
  }, [fetchJson, persist, refreshLive]);

  const create = useCallback(async () => {
    if (!points?.length || !t0 || creatingRef.current) return null;
    creatingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const body = await fetchJson("/voyage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          t0,
          expedition_id: expeditionId || "berry-mappemonde-2026",
          routeKind: routeKind || "berry",
          follow: Boolean(follow),
          forecast: Boolean(forecast),
          startAt,
          points: points.map((p) => ({
            lat: p.lat,
            lon: p.lon,
            cumNm: p.cumNm,
            filmCum: p.filmCum,
            jump: Boolean(p.jump),
            nonMaritime: Boolean(p.nonMaritime),
          })),
          marks: (marks || []).map((m) => ({
            name: m.name,
            nm: m.nm,
            filmNm: m.filmNm,
            lat: m.lat,
            lon: m.lon,
            index: m.index,
            flag: true,
          })),
        }),
      });
      setVoyage(body);
      clockRef.current = body.clock || null;
      setClock(body.clock || null);
      persist(body);
      fpRef.current = fingerprint(points, t0, startAt);
      failCountRef.current = 0;
      nextCreateAtRef.current = 0;
      if (shouldFetchAt(body.clock)) {
        await refreshLive(body.voyageId, body.clock);
      }
      return body;
    } catch (err) {
      failCountRef.current += 1;
      nextCreateAtRef.current = Date.now() + createBackoffMs(failCountRef.current);
      setError(String(err.message || err));
      return null;
    } finally {
      creatingRef.current = false;
      setBusy(false);
    }
  }, [points, t0, startAt, expeditionId, routeKind, follow, forecast, marks, fetchJson, persist, refreshLive]);

  useEffect(() => {
    if (!enabled || !points?.length || !t0) return undefined;
    const fp = fingerprint(points, t0, startAt);
    const stored = readStored();
    let cancelled = false;

    const boot = async () => {
      if (fpRef.current === fp && voyage?.voyageId) {
        await refreshMeta(voyage.voyageId);
        return;
      }
      if (stored?.voyageId && stored.t0 === t0) {
        try {
          const meta = await refreshMeta(stored.voyageId);
          if (!cancelled && meta) {
            fpRef.current = fp;
            failCountRef.current = 0;
            nextCreateAtRef.current = 0;
            return;
          }
        } catch { /* recreate */ }
      }
      if (lastAttemptFpRef.current !== fp) {
        lastAttemptFpRef.current = fp;
        failCountRef.current = 0;
        nextCreateAtRef.current = 0;
      }
      const wait = nextCreateAtRef.current - Date.now();
      if (wait > 0) {
        retryTimerRef.current = setTimeout(() => {
          retryTimerRef.current = null;
          if (!cancelled) create();
        }, wait);
        return;
      }
      lastAttemptFpRef.current = fp;
      if (!cancelled) await create();
    };
    boot();
    return () => {
      cancelled = true;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [enabled, points, t0, startAt]); // eslint-line — create/refresh via refs

  useEffect(() => {
    if (!enabled || !follow || !voyage?.voyageId) return undefined;
    const tick = () => {
      if (!shouldFetchAt(clockRef.current)) return;
      refreshLive(voyage.voyageId).catch(() => {});
    };
    // Suivre sur ma route : la position « à maintenant » se lit dès
    // l'entrée en suivi, pas seulement au premier tic de 60 s.
    tick();
    const id = setInterval(tick, 60_000);
    const onFocus = () => tick();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled, follow, voyage?.voyageId, refreshLive]);

  useEffect(() => {
    if (!enabled || !voyage?.voyageId) return undefined;
    if (voyage.forecastStatus !== "pending") return undefined;
    const id = setInterval(() => {
      refreshMeta(voyage.voyageId).catch(() => {});
    }, 2500);
    return () => clearInterval(id);
  }, [enabled, voyage?.voyageId, voyage?.forecastStatus, refreshMeta]);

  /**
   * Route advice: `constraints` = { windMaxKt, hsMaxM } from the
   * skipper's orders — the isochrone never steps into a wind or a sea above them.
   */
  const recompute = useCallback(async (fromIso, constraints = null) => {
    if (!voyage?.voyageId) return null;
    setBusy(true);
    try {
      const body = { ...(fromIso ? { t: fromIso } : {}) };
      if (Number.isFinite(constraints?.windMaxKt)) body.wind_max_kt = constraints.windMaxKt;
      if (Number.isFinite(constraints?.hsMaxM)) body.hs_max_m = constraints.hsMaxM;
      const d = await fetchJson(`/voyage/${voyage.voyageId}/recompute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setDraft(d);
      return d;
    } finally {
      setBusy(false);
    }
  }, [voyage?.voyageId, fetchJson]);

  const accept = useCallback(async () => {
    if (!voyage?.voyageId) return null;
    setBusy(true);
    try {
      const body = await fetchJson(`/voyage/${voyage.voyageId}/accept`, { method: "POST" });
      setVoyage(body);
      clockRef.current = body.clock || null;
      setClock(body.clock || null);
      setDraft(null);
      persist(body);
      if (shouldFetchAt(body.clock)) {
        await refreshLive(body.voyageId, body.clock);
      }
      return body;
    } finally {
      setBusy(false);
    }
  }, [voyage?.voyageId, fetchJson, persist, refreshLive]);

  const reject = useCallback(async () => {
    if (!voyage?.voyageId) return;
    await fetchJson(`/voyage/${voyage.voyageId}/reject`, { method: "POST" });
    setDraft(null);
  }, [voyage?.voyageId, fetchJson]);

  const refreshForecast = useCallback(async () => {
    if (!voyage?.voyageId) return;
    await fetchJson(`/voyage/${voyage.voyageId}/refresh-forecast`, { method: "POST" });
    await refreshMeta(voyage.voyageId);
  }, [voyage?.voyageId, fetchJson, refreshMeta]);

  return {
    voyage,
    live,
    clock,
    draft,
    error,
    busy,
    forecastStatus: voyage?.forecastStatus || (forecast ? "pending" : "unavailable"),
    create,
    refreshLive,
    recompute,
    accept,
    reject,
    refreshForecast,
  };
}

/**
 * Phrase d'explication du recalcul. Les nombres viennent du
 * serveur (`draft.advice.delta`) ; le LLM n'en invente pas.
 */
export function RouteAdviceText({ draft }) {
  const text = typeof draft?.advice?.text === "string" ? draft.advice.text.trim() : "";
  if (!text) return null;
  return createElement(
    "p",
    {
      "data-testid": "route-advice-text",
      className: "text-[10px] text-cyan-100/85 leading-snug mb-2",
    },
    text,
  );
}
