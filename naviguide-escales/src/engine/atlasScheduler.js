/**
 * Atlas scheduler — decides WHO asks Blue Intelligence for climatology and WHEN.
 * Pure module (no React, no fetch of its own) so the rules are unit-tested.
 *
 * Incident 2026-09-21: the film ticks several times per second; the old hook
 * aborted and restarted its fetches on every tick → 600-800 req/s on the VPS,
 * nginx saturated (768 connections), backend « Too many open files »,
 * Cloudflare 500 / 525, empty ici() bag. Rules that make it impossible:
 *
 *  - one request per cell per session: dedup in flight, never abort on a tick;
 *  - route prefetch bounded (≤ 48 points × 3 months), independent of the boat;
 *  - boat cell (+ cyclone crossings ≈ 1 s CPU on the backend): at most one
 *    request every BOAT_MIN_INTERVAL_MS, and only when the boat changes cell;
 *  - atlas down (network, 5xx, 429): no retry before DOWN_COOLDOWN_MS.
 *
 * kind stays "climatology"; a missing cell is served by the zone fallback.
 */

import {
  atlasCrossingsUrl,
  atlasPointUrl,
  cellKey,
  clampMonth,
  windFromAtlasPoint,
} from "../utils/atlasPoint.js";
import { monthOfT0 } from "./voyageClock.js";

export const CONCURRENCY = 6;
export const DOWN_COOLDOWN_MS = 30_000;
export const BOAT_MIN_INTERVAL_MS = 1500;
export const ROUTE_SAMPLES = 48;

/** Route cells to warm: ≤ ROUTE_SAMPLES points × the 3 months around t0. */
export function routeCells(points, t0) {
  const m0 = monthOfT0(t0, 0);
  const months = [m0, clampMonth(m0 + 1), clampMonth(m0 + 2)];
  const cells = new Map();
  const pts = points || [];
  const step = Math.max(1, Math.ceil(pts.length / ROUTE_SAMPLES));
  for (let i = 0; i < pts.length; i += step) {
    const p = pts[i];
    if (!p || p.jump || p.nonMaritime) continue;
    if (!Number.isFinite(Number(p.lat)) || !Number.isFinite(Number(p.lon))) continue;
    months.forEach((m) => {
      const key = cellKey(p.lat, p.lon, m);
      if (!cells.has(key)) cells.set(key, { lat: p.lat, lon: p.lon, month: m });
    });
  }
  return [...cells.values()];
}

/** Errors that mean « leave the atlas alone for a while ». */
export function isDownError(err) {
  const status = Number(err?.status);
  if (Number.isFinite(status) && status > 0) return status >= 500 || status === 429;
  const msg = String(err?.message || err || "");
  return /Failed to fetch|NetworkError|Load failed|ECONNREFUSED|ECONNRESET|fetch failed/i.test(msg);
}

function entryFor(point) {
  const wind = windFromAtlasPoint(point);
  return { point, wind, source: wind ? "atlas" : "empty" };
}

const FALLBACK = Object.freeze({ point: null, wind: null, source: "zone_fallback" });

/**
 * @param {object} opts
 * @param {(url: string) => Promise<object>} opts.fetchJson — rejects with `.status` on HTTP errors
 * @param {() => number} [opts.now]
 */
export function createAtlasScheduler({
  fetchJson,
  now = () => Date.now(),
  concurrency = CONCURRENCY,
  cooldownMs = DOWN_COOLDOWN_MS,
  boatMinIntervalMs = BOAT_MIN_INTERVAL_MS,
} = {}) {
  if (typeof fetchJson !== "function") throw new TypeError("fetchJson required");
  const cache = new Map();
  const inflight = new Map();
  const listeners = new Set();
  const stats = { requests: 0, downs: 0 };
  let downUntil = 0;
  let boatDoneKey = "";
  let boatInflightKey = "";
  let lastBoatStart = -Infinity;

  const emit = (event) => {
    listeners.forEach((fn) => {
      try { fn(event); } catch { /* a listener must never break the scheduler */ }
    });
  };
  const isDown = () => now() < downUntil;
  const markDown = () => {
    downUntil = now() + cooldownMs;
    stats.downs += 1;
    emit({ type: "down", until: downUntil });
  };

  async function fetchCell(cell) {
    const key = cellKey(cell.lat, cell.lon, cell.month);
    if (cache.has(key)) return cache.get(key);
    if (inflight.has(key)) return inflight.get(key);
    stats.requests += 1;
    const work = fetchJson(atlasPointUrl(cell))
      .then((point) => {
        const entry = entryFor(point);
        cache.set(key, entry);
        emit({ type: "cell", key, entry });
        return entry;
      })
      .catch((err) => {
        if (isDownError(err)) {
          if (!isDown()) markDown();
          return null; // not cached → retried after the cooldown
        }
        cache.set(key, FALLBACK); // 4xx: this cell will never answer
        return FALLBACK;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, work);
    return work;
  }

  // One queue for the whole tab: `concurrency` requests on the wire, whoever asks.
  const queue = [];
  const waiters = new Map(); // key → { promise, resolve } while queued / running
  let active = 0;

  function pump() {
    while (active < concurrency && queue.length) {
      const cell = queue.shift();
      const key = cellKey(cell.lat, cell.lon, cell.month);
      const waiter = waiters.get(key);
      active += 1;
      const run = isDown() ? Promise.resolve(null) : fetchCell(cell);
      run.then(
        (entry) => { waiters.delete(key); waiter?.resolve(entry); },
        () => { waiters.delete(key); waiter?.resolve(null); },
      ).finally(() => {
        active -= 1;
        pump();
      });
    }
  }

  /**
   * Warm the route cells. Never aborted: a late answer still fills the cache.
   * Cells skipped because the atlas is down are counted in `deferred`.
   */
  async function prefetch(cells) {
    const outcomes = [];
    (cells || []).forEach((cell) => {
      const key = cellKey(cell.lat, cell.lon, cell.month);
      if (cache.has(key)) return;
      if (inflight.has(key)) { outcomes.push(inflight.get(key)); return; }
      if (waiters.has(key)) { outcomes.push(waiters.get(key).promise); return; }
      let resolve;
      const promise = new Promise((r) => { resolve = r; });
      waiters.set(key, { promise, resolve });
      queue.push(cell);
      outcomes.push(promise);
    });
    pump();
    const results = await Promise.all(outcomes);
    const fetched = results.filter(Boolean).length;
    return { fetched, deferred: results.length - fetched, total: results.length };
  }

  /**
   * Boat cell (+ crossings towards the destination). Returns what happened:
   *  done | inflight | started | wait(waitMs) | down(waitMs).
   */
  function boat({ lat, lon, month, destLat, destLon }) {
    if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return { status: "skip" };
    const m = clampMonth(month);
    const hasDest = Number.isFinite(Number(destLat)) && Number.isFinite(Number(destLon));
    const cell = cellKey(lat, lon, m);
    const key = `${cell}:${hasDest ? `${destLat}:${destLon}` : ""}`;
    if (key === boatInflightKey) return { status: "inflight", key };
    if (key === boatDoneKey) return { status: "done", key };
    if (isDown()) return { status: "down", key, waitMs: Math.max(0, downUntil - now()) };
    const elapsed = now() - lastBoatStart;
    if (elapsed < boatMinIntervalMs) return { status: "wait", key, waitMs: boatMinIntervalMs - elapsed };

    boatInflightKey = key;
    lastBoatStart = now();
    stats.requests += hasDest ? 2 : 1;
    const spec = { lat, lon, month: m, destLat: hasDest ? destLat : undefined, destLon: hasDest ? destLon : undefined };
    const pointReq = fetchJson(atlasPointUrl(spec));
    const crossings = hasDest
      ? fetchJson(atlasCrossingsUrl({ lat1: lat, lon1: lon, lat2: destLat, lon2: destLon, month: m })).catch(() => null)
      : Promise.resolve(null);
    Promise.all([pointReq, crossings])
      .then(([point, cross]) => {
        const packed = cross ? { ...point, crossings: cross } : point;
        if (packed?.cyclone && cross && !packed.cyclone.crossings_if_leg) {
          packed.cyclone = { ...packed.cyclone, crossings_if_leg: cross };
        }
        const entry = entryFor(packed);
        cache.set(cell, entry);
        boatDoneKey = key;
        emit({ type: "boat", key, cell, point: packed, entry });
      })
      .catch((err) => {
        if (isDownError(err)) {
          if (!isDown()) markDown();
        } else {
          boatDoneKey = key; // 4xx: do not ask again for this cell
          if (!cache.has(cell)) cache.set(cell, FALLBACK);
        }
      })
      .finally(() => {
        if (boatInflightKey === key) boatInflightKey = "";
      });
    return { status: "started", key };
  }

  function reset() {
    cache.clear();
    inflight.clear();
    queue.splice(0).forEach((cell) => {
      const key = cellKey(cell.lat, cell.lon, cell.month);
      waiters.get(key)?.resolve(null);
      waiters.delete(key);
    });
    downUntil = 0;
    boatDoneKey = "";
    boatInflightKey = "";
    lastBoatStart = -Infinity;
    stats.requests = 0;
    stats.downs = 0;
  }

  return {
    cache,
    inflight,
    stats,
    isDown,
    downUntil: () => downUntil,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    prefetch,
    boat,
    reset,
  };
}
