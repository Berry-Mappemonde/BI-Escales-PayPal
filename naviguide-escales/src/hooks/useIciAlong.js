import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ROUTE_SAMPLE_NM } from "../engine/eventRules.js";
import {
  SIM_FAR_STEP_NM,
  SIM_NEAR_NM,
  buildAlongIndex,
  canonicalWindow,
  flatFromCustomRoute,
  lookaheadNmFor,
  maxPearlsFor,
  nearestPearlBag,
  pearlKey,
  sampleLeg,
} from "../engine/iciAlong.js";
import { wrapLon } from "../utils/geo.js";

const API_URL = import.meta.env?.VITE_API_URL ?? "";
const FETCH_MS = 20000;
const PARALLEL = 4;
/** Two pearls behind the boat stay in the window: the one just passed is the live thin bag. */
const BEHIND_NM = 2 * ROUTE_SAMPLE_NM;

/** The canonical pearls of the official route are the same for every visitor: one GET per tab. */
let canonicalPromise = null;
function loadCanonicalPearls() {
  if (!canonicalPromise) {
    canonicalPromise = fetch(`${API_URL}/ici/pearls`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => (Array.isArray(data?.pearls) && data.pearls.length ? data.pearls : null))
      .catch(() => null);
  }
  return canonicalPromise;
}

/**
 * Preheat thin /ici pearls on THIS leg. Never blocks Play. No chat.
 * Suivre cap = hours × planning knots from the skipper orders; pearls follow (§2.6).
 * Never the whole route.
 *
 * The pearl cache lives for the whole route (not one leg): a replay or a
 * leg change costs nothing, and `nearestBag()` gives the detectors a thin bag
 * at the boat at any film speed while the full bag is still on its way.
 */
export function useIciAlong({
  enabled,
  flat,
  /** Drawn route: always sample this track, never the official pearls. */
  customRoute = null,
  fromNm,
  toNm,
  boatNm,
  boatLat = null,
  boatLon = null,
  mode = "simulation",
  month,
  orders = null,
  /** Berry route: sample the server's canonical pearls (warmed cache). Drawn route: own sampling. */
  canonical = false,
}) {
  const [bags, setBags] = useState(() => new Map());
  const [canonicalPearls, setCanonicalPearls] = useState(null);
  const cacheRef = useRef(new Map());
  const drawnFlat = useMemo(() => flatFromCustomRoute(customRoute), [customRoute]);
  const track = drawnFlat || flat;
  const alongCanonical = Boolean(canonical && !drawnFlat);
  const routeKey = `${drawnFlat ? "c" : "o"}:${track?.points?.length || 0}:${track?.totalNm || 0}:${mode}`;
  const lastRouteRef = useRef(routeKey);
  if (lastRouteRef.current !== routeKey) {
    lastRouteRef.current = routeKey;
    cacheRef.current = new Map();
  }

  useEffect(() => {
    if (!enabled || !alongCanonical) return undefined;
    let cancelled = false;
    loadCanonicalPearls().then((list) => { if (!cancelled) setCanonicalPearls(list); });
    return () => { cancelled = true; };
  }, [enabled, alongCanonical]);

  const boatBucket = Number.isFinite(Number(boatNm))
    ? Math.floor(Number(boatNm) / ROUTE_SAMPLE_NM) * ROUTE_SAMPLE_NM
    : 0;
  // The window moves by whole pearls: round the boat position to ~1 nm.
  const latB = Number.isFinite(Number(boatLat)) ? Math.round(Number(boatLat) * 60) / 60 : null;
  const lonB = Number.isFinite(Number(boatLon)) ? Math.round(wrapLon(Number(boatLon)) * 60) / 60 : null;

  const lookaheadNm = lookaheadNmFor(mode, orders);
  const maxPearls = maxPearlsFor(mode, orders);

  const pearls = useMemo(() => {
    if (!enabled || !track?.points?.length) return [];
    if (alongCanonical && canonicalPearls) {
      return canonicalWindow(canonicalPearls, track, {
        boatNm: boatBucket,
        boatLat: latB,
        boatLon: lonB,
        toNm,
        maxPearls,
        lookaheadNm,
        month,
        nearCount: mode === "suivre" ? Infinity : Math.round(SIM_NEAR_NM / ROUTE_SAMPLE_NM),
        farEvery: Math.round(SIM_FAR_STEP_NM / ROUTE_SAMPLE_NM),
      });
    }
    return sampleLeg(track, {
      fromNm,
      toNm,
      boatNm: boatBucket,
      month,
      lookaheadNm,
      maxPearls,
      behindNm: BEHIND_NM,
      // Simulation: the whole leg, dense near the boat, coarser far ahead.
      nearNm: mode === "suivre" ? Infinity : SIM_NEAR_NM,
      farStepNm: mode === "suivre" ? null : SIM_FAR_STEP_NM,
    });
  }, [enabled, track, fromNm, toNm, boatBucket, latB, lonB, month, lookaheadNm, maxPearls, mode, alongCanonical, canonicalPearls]);

  const pearlsSig = pearls.map((p) => pearlKey(p.lat, p.lon, month)).join("|");

  useEffect(() => {
    if (!enabled || !pearls.length) return undefined;
    let cancelled = false;
    const missing = pearls.filter((p) => !cacheRef.current.has(pearlKey(p.lat, p.lon, month)));
    if (!missing.length) {
      setBags(new Map(cacheRef.current));
      return undefined;
    }
    // A small pool: PARALLEL requests in flight, the next one starts as soon
    // as one lands (a cached pearl answers in ms, a cold one in seconds —
    // chunking made the fast ones wait for the slow ones).
    let next = 0;
    let publishTimer = null;
    const inflight = [];
    const publish = () => {
      if (cancelled || publishTimer) return;
      publishTimer = setTimeout(() => {
        publishTimer = null;
        if (!cancelled) setBags(new Map(cacheRef.current));
      }, 150);
    };
    const fetchOne = async (p) => {
      const key = pearlKey(p.lat, p.lon, month);
      if (cacheRef.current.has(key)) return;
      const ctrl = new AbortController();
      inflight.push(ctrl);
      const kill = setTimeout(() => ctrl.abort(), FETCH_MS);
      try {
        const q = new URLSearchParams({
          lat: String(p.lat),
          lon: String(wrapLon(Number(p.lon))),
          thin: "1",
        });
        if (Number.isFinite(Number(month))) q.set("month", String(month));
        const r = await fetch(`${API_URL}/ici?${q.toString()}`, { signal: ctrl.signal });
        const data = r.ok ? await r.json() : null;
        if (!cancelled) cacheRef.current.set(key, data);
      } catch {
        if (!cancelled) cacheRef.current.set(key, null);
      } finally {
        clearTimeout(kill);
        publish();
      }
    };
    const worker = async () => {
      while (!cancelled && next < missing.length) {
        const p = missing[next];
        next += 1;
        await fetchOne(p);
      }
    };
    Promise.all(Array.from({ length: Math.min(PARALLEL, missing.length) }, worker)).catch(() => {});
    return () => {
      cancelled = true;
      for (const c of inflight) c.abort();
      clearTimeout(publishTimer);
    };
  }, [enabled, pearlsSig, month]);

  const index = useMemo(
    () => buildAlongIndex(pearls, bags, month, orders),
    [pearls, bags, month, orders],
  );

  const nearestBag = useCallback(
    (boat, maxNm = 15) => nearestPearlBag(pearls, bags, boat, { maxNm, month }),
    [pearls, bags, month],
  );

  return {
    index,
    pearls,
    nearestBag,
    loading: Boolean(enabled && pearls.length && pearls.some((p) => !bags.has(pearlKey(p.lat, p.lon, month)))),
  };
}
