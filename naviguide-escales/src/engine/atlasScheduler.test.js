import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BOAT_MIN_INTERVAL_MS,
  DOWN_COOLDOWN_MS,
  ROUTE_SAMPLES,
  createAtlasScheduler,
  isDownError,
  routeCells,
} from "./atlasScheduler.js";

const here = dirname(fileURLToPath(import.meta.url));

const POINT = {
  kind: "climatology",
  month: 9,
  wind_atlas: { most_likely: { speed_knots: 15, dir_deg: 270 }, vector_mean: { speed_knots: 12, dir_deg: 260 } },
  cyclone: { nearby: 0, tracks_in_month: 3, crossings_if_leg: null },
};

/** Fake network: every call is recorded; answers are released by hand. */
function fakeNet({ auto = true } = {}) {
  const calls = [];
  const pending = [];
  const fetchJson = (url) => {
    calls.push(url);
    if (auto) return Promise.resolve(url.includes("/crossings?") ? { count: 1 } : { ...POINT });
    return new Promise((resolve, reject) => pending.push({ url, resolve, reject }));
  };
  const flush = () => {
    pending.splice(0).forEach((p) => p.resolve(p.url.includes("/crossings?") ? { count: 1 } : { ...POINT }));
  };
  return { calls, pending, flush, fetchJson };
}

function clock(start = 1_000_000) {
  let t = start;
  return { now: () => t, tick: (ms) => { t += ms; } };
}

const tickAsync = () => new Promise((r) => setTimeout(r, 0));

// A leg Saint-Maur → La Rochelle, 200 points: the old hook could send them all again on every tick.
const ROUTE = Array.from({ length: 200 }, (_, i) => ({ lat: 46.7 - i * 0.003, lon: 1.5 - i * 0.014 }));
const T0 = "2026-09-21T08:00:00Z";

describe("atlasScheduler — the 2026-09-21 storm cannot happen again", () => {
  it("route prefetch is bounded: ≤ 48 points × 3 months, one request per cell, never twice", async () => {
    const net = fakeNet();
    const s = createAtlasScheduler({ fetchJson: net.fetchJson });
    const cells = routeCells(ROUTE, T0);
    assert.ok(cells.length <= ROUTE_SAMPLES * 3, `too many cells: ${cells.length}`);
    const first = await s.prefetch(cells);
    assert.equal(first.fetched, cells.length);
    assert.equal(net.calls.length, cells.length);
    // The film ticks: the same route asked 100 more times costs nothing.
    for (let i = 0; i < 100; i += 1) await s.prefetch(cells);
    assert.equal(net.calls.length, cells.length, "a warm route must not refetch");
  });

  it("concurrency is capped and in-flight cells are shared (no duplicate fetch while pending)", async () => {
    const net = fakeNet({ auto: false });
    const s = createAtlasScheduler({ fetchJson: net.fetchJson, concurrency: 6 });
    const cells = routeCells(ROUTE, T0);
    const p1 = s.prefetch(cells);
    await tickAsync();
    assert.equal(net.pending.length, 6, "at most 6 requests on the wire");
    const p2 = s.prefetch(cells); // second caller while the first is in flight
    await tickAsync();
    assert.equal(net.pending.length, 6, "the second caller adds no request");
    while (net.pending.length) { net.flush(); await tickAsync(); await tickAsync(); }
    await Promise.all([p1, p2]);
    assert.equal(net.calls.length, cells.length);
  });

  it("boat: 100 ticks inside one cell = 1 point + 1 crossings, nothing aborted", async () => {
    const net = fakeNet();
    const c = clock();
    const s = createAtlasScheduler({ fetchJson: net.fetchJson, now: c.now });
    const dest = { destLat: 46.16, destLon: -1.15 };
    let started = 0;
    for (let i = 0; i < 100; i += 1) {
      const r = s.boat({ lat: 46.30 + i * 0.0005, lon: -1.30 + i * 0.0005, month: 9, ...dest });
      if (r.status === "started") started += 1;
      c.tick(100);
      await tickAsync();
    }
    assert.equal(started, 1);
    assert.equal(net.calls.length, 2, "one point (with dest) + one crossings");
    assert.match(net.calls[0], /\/climatology\/point\?.*dest_lat=46\.16/);
    assert.match(net.calls[1], /\/climatology\/crossings\?/);
  });

  it("boat: a fast film crossing 10 cells in a second is throttled to one request per interval", async () => {
    const net = fakeNet();
    const c = clock();
    const s = createAtlasScheduler({ fetchJson: net.fetchJson, now: c.now });
    const statuses = [];
    for (let i = 0; i < 10; i += 1) {
      // 1° per tick = a new 0.5° cell every tick
      statuses.push(s.boat({ lat: 10 + i, lon: -30, month: 9 }).status);
      c.tick(100);
      await tickAsync();
    }
    assert.equal(statuses[0], "started");
    assert.ok(statuses.slice(1).every((st) => st === "wait"), `expected wait, got ${statuses}`);
    assert.equal(net.calls.length, 1);
    c.tick(BOAT_MIN_INTERVAL_MS);
    assert.equal(s.boat({ lat: 19, lon: -30, month: 9 }).status, "started");
    assert.equal(net.calls.length, 2);
  });

  it("boat: an answer that lands after the boat moved on still fills the cache and is published", async () => {
    const net = fakeNet({ auto: false });
    const c = clock();
    const s = createAtlasScheduler({ fetchJson: net.fetchJson, now: c.now });
    const events = [];
    s.subscribe((e) => events.push(e));
    assert.equal(s.boat({ lat: 46.1, lon: -1.2, month: 9 }).status, "started");
    c.tick(BOAT_MIN_INTERVAL_MS + 1);
    assert.equal(s.boat({ lat: 47.1, lon: -2.2, month: 9 }).status, "started");
    net.flush();
    await tickAsync(); await tickAsync();
    assert.equal(events.filter((e) => e.type === "boat").length, 2);
    assert.ok(s.cache.has("46:-1:9"));
    assert.ok(s.cache.has("47:-2:9"));
  });

  it("atlas down (5xx / network): one failure opens a cooldown, nothing is asked until it ends", async () => {
    const calls = [];
    let failing = true;
    const fetchJson = (url) => {
      calls.push(url);
      if (failing) { const e = new Error("atlas 502"); e.status = 502; return Promise.reject(e); }
      return Promise.resolve({ ...POINT });
    };
    const c = clock();
    const s = createAtlasScheduler({ fetchJson, now: c.now, concurrency: 1 });
    const downs = [];
    s.subscribe((e) => { if (e.type === "down") downs.push(e); });
    const cells = routeCells(ROUTE, T0);
    const res = await s.prefetch(cells);
    assert.equal(calls.length, 1, "the first 5xx stops the wave");
    assert.equal(res.deferred, cells.length);
    assert.equal(downs.length, 1);
    assert.ok(s.isDown());
    // Ticks during the cooldown: boat and route both stay silent.
    assert.equal(s.boat({ lat: 46.1, lon: -1.2, month: 9 }).status, "down");
    await s.prefetch(cells);
    assert.equal(calls.length, 1);
    // Cooldown over, atlas back: cells are fetched (nothing was cached as a failure).
    c.tick(DOWN_COOLDOWN_MS + 1);
    failing = false;
    const again = await s.prefetch(cells);
    assert.equal(again.fetched, cells.length);
    assert.equal(s.isDown(), false);
  });

  it("a 4xx cell is remembered as zone_fallback, not retried, and does not mark the atlas down", async () => {
    const calls = [];
    const fetchJson = (url) => { calls.push(url); const e = new Error("atlas 400"); e.status = 400; return Promise.reject(e); };
    const s = createAtlasScheduler({ fetchJson });
    const cells = [{ lat: 95, lon: 0, month: 9 }];
    await s.prefetch(cells);
    await s.prefetch(cells);
    assert.equal(calls.length, 1);
    assert.equal(s.cache.get("95:0:9").source, "zone_fallback");
    assert.equal(s.isDown(), false);
  });

  it("isDownError: 5xx, 429 and network failures; not 4xx", () => {
    assert.equal(isDownError(Object.assign(new Error("x"), { status: 503 })), true);
    assert.equal(isDownError(Object.assign(new Error("x"), { status: 429 })), true);
    assert.equal(isDownError(new TypeError("Failed to fetch")), true);
    assert.equal(isDownError(Object.assign(new Error("x"), { status: 404 })), false);
    assert.equal(isDownError(Object.assign(new Error("x"), { status: 400 })), false);
  });

  it("reset clears the cache, the cooldown and the boat memory", async () => {
    const net = fakeNet();
    const s = createAtlasScheduler({ fetchJson: net.fetchJson });
    await s.prefetch(routeCells(ROUTE, T0));
    s.boat({ lat: 46.1, lon: -1.2, month: 9 });
    await tickAsync();
    assert.ok(s.cache.size > 0);
    s.reset();
    assert.equal(s.cache.size, 0);
    assert.equal(s.boat({ lat: 46.1, lon: -1.2, month: 9 }).status, "started");
  });
});

describe("useAtlasLookup wiring (contract)", () => {
  const hook = readFileSync(join(here, "..", "hooks", "useAtlasLookup.js"), "utf8");

  it("delegates the rules to the scheduler and never aborts a request on a tick", () => {
    assert.match(hook, /createAtlasScheduler\(\{ fetchJson \}\)/);
    assert.match(hook, /scheduler\.subscribe\(/);
    assert.match(hook, /scheduler\.prefetch\(routeCells\(points, t0\)\)/);
    assert.match(hook, /scheduler\.boat\(\{/);
    assert.doesNotMatch(hook, /AbortController|\.abort\(\)/);
  });

  it("route prefetch does not depend on the boat position", () => {
    const deps = hook.match(/\[enabled, t0, points, month, retryTick\]/);
    assert.ok(deps, "prefetch effect deps must be [enabled, t0, points, month, retryTick]");
  });
});
