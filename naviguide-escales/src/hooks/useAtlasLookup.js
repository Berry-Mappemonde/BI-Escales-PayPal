import { useCallback, useEffect, useState } from "react";
import { atlasOrZone, cellKey, clampMonth } from "../utils/atlasPoint.js";
import { monthOfT0 } from "../engine/voyageClock.js";
import { createAtlasScheduler, routeCells } from "../engine/atlasScheduler.js";

/**
 * Browser fetch → JSON; HTTP errors carry `.status` so the scheduler can tell
 * « atlas down » (5xx / 429 / network) from « this cell never answers » (4xx).
 */
/** Réponse BI muette : pas un point d'atlas. Le scheduler la traite comme une panne. */
export function atlasNoticeFromBody(body) {
  if (!body || typeof body !== "object") return null;
  if (body.status === "unavailable" || body.kind === "unavailable") {
    return { unavailable: true, source: null, period: null };
  }
  const period = body.period || body.periods?.cyclone || body.periods?.wind || null;
  const tracks = body.ibtracsCount ?? body.cyclone?.tracks_in_month;
  const count = Number(tracks);
  const hasTraces = Number.isFinite(count) && count > 0;
  if (!period && !hasTraces && body.kind !== "climatology") return null;
  return {
    unavailable: false,
    source: hasTraces ? "IBTrACS" : (body.source || (body.kind === "climatology" ? "atlas" : null)),
    period: period || null,
  };
}

const atlasNotice = { unavailable: false, source: null, period: null };
const noticeListeners = new Set();

export function publishAtlasNotice(partial) {
  if (!partial) return atlasNotice;
  Object.assign(atlasNotice, partial);
  const snap = { ...atlasNotice };
  noticeListeners.forEach((fn) => {
    try { fn(snap); } catch { /* un écouteur ne casse pas les autres */ }
  });
  return snap;
}

export function resetAtlasNotice() {
  atlasNotice.unavailable = false;
  atlasNotice.source = null;
  atlasNotice.period = null;
  noticeListeners.forEach((fn) => {
    try { fn({ ...atlasNotice }); } catch { /* idem */ }
  });
}

export function useAtlasNotice() {
  const [snap, setSnap] = useState(() => ({ ...atlasNotice }));
  useEffect(() => {
    noticeListeners.add(setSnap);
    setSnap({ ...atlasNotice });
    return () => noticeListeners.delete(setSnap);
  }, []);
  return snap;
}

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const err = new Error(`atlas ${r.status}`);
    err.status = r.status;
    throw err;
  }
  const body = await r.json();
  const notice = atlasNoticeFromBody(body);
  if (notice?.unavailable) {
    publishAtlasNotice(notice);
    const err = new Error("atlas unavailable");
    err.status = 503;
    throw err;
  }
  if (notice && (notice.period || notice.source)) publishAtlasNotice(notice);
  return body;
}

// One scheduler per tab: the cache and the in-flight table are shared by
// every mount, and by resetAtlasCache() (tests, new voyage).
const scheduler = createAtlasScheduler({ fetchJson });

/**
 * Session cache of /climatology/point. Sync lookup for the clock;
 * async fill replaces zone_fallback as cells arrive.
 *
 * The React side only listens: the rules (dedup, no abort per tick, boat
 * interval, cooldown when the atlas is down) live in engine/atlasScheduler.js.
 */
export function useAtlasLookup({
  enabled = true,
  t0,
  points = [],
  boatLat,
  boatLon,
  destLat,
  destLon,
  month,
} = {}) {
  const [revision, setRevision] = useState(0);
  const [boatPoint, setBoatPoint] = useState(null);
  const [alive, setAlive] = useState(null);
  const [retryTick, setRetryTick] = useState(0);
  const [boatTick, setBoatTick] = useState(0);

  const windAt = useCallback((lat, lon, m) => {
    const hit = scheduler.cache.get(cellKey(lat, lon, m));
    return atlasOrZone(lat, lon, m, hit?.point || null);
  }, []);

  const lookup = useCallback((lat, lon, m) => {
    return scheduler.cache.get(cellKey(lat, lon, m)) || null;
  }, []);

  // One subscription per mount: cells and boat answers land here whenever
  // they arrive, even after the boat moved on (nothing is aborted).
  useEffect(() => {
    if (!enabled) return undefined;
    return scheduler.subscribe((event) => {
      if (event.type === "down") {
        setAlive(false);
        publishAtlasNotice({ unavailable: true, source: null, period: null });
        return;
      }
      if (event.type === "boat") setBoatPoint(event.point);
      const point = event.entry?.point || event.point;
      const notice = atlasNoticeFromBody(point);
      if (notice?.unavailable) {
        setAlive(false);
        publishAtlasNotice(notice);
      } else if (notice && (notice.period || notice.source)) {
        if (event.entry?.source === "atlas" || notice.source) setAlive(true);
        publishAtlasNotice(notice);
      } else if (event.entry?.source === "atlas") {
        setAlive(true);
      }
      setRevision((n) => n + 1);
    });
  }, [enabled]);

  // Route prefetch: depends on the route and the clock, never on the boat.
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    let timer = null;
    scheduler.prefetch(routeCells(points, t0)).then((res) => {
      if (!active || res.deferred === 0) return;
      const wait = Math.max(250, scheduler.downUntil() - Date.now() + 50);
      timer = setTimeout(() => setRetryTick((n) => n + 1), wait);
    }).catch(() => {});
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, t0, points, month, retryTick]);

  // Boat cell (+ crossings): once per cell, at most one request per interval.
  useEffect(() => {
    if (!enabled || !Number.isFinite(Number(boatLat))) return undefined;
    const m = clampMonth(month || monthOfT0(t0, 0));
    const res = scheduler.boat({ lat: boatLat, lon: boatLon, month: m, destLat, destLon });
    if (res.status !== "wait" && res.status !== "down") return undefined;
    const timer = setTimeout(() => setBoatTick((n) => n + 1), Math.max(100, res.waitMs || 0));
    return () => clearTimeout(timer);
  }, [enabled, boatLat, boatLon, destLat, destLon, month, t0, boatTick]);

  return {
    windAt,
    lookup,
    boatPoint,
    revision,
    alive,
  };
}

export function resetAtlasCache() {
  scheduler.reset();
  resetAtlasNotice();
}
