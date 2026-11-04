/**
 * Lookahead on the planned GPS track of THIS leg.
 * Pearls every ROUTE_SAMPLE_NM. Not the globe. No chat.
 *
 * Suivre horizon never lies (§2.6): cap nm = hours × planning knots,
 * pearls = ceil(nm / 12). Both follow the skipper orders. No fixed 350 / 24.
 */

import { flattenRoute, interpolateAtNm, nearestNm } from "./routePlayhead.js";
import { featuresToSegments, haversineNm } from "../utils/geo.js";
import {
  AMP_AHEAD_MIN_NM,
  ROUTE_SAMPLE_NM,
  MARINA_REFUGE_NM,
} from "./eventRules.js";
import { DEFAULT_ORDERS, lookaheadBudget, thresholdValues } from "./skipperOrders.js";

export { AMP_AHEAD_MIN_NM };
export const ALONG_AMP_NM = 15;
export const ALONG_MARINA_NM = MARINA_REFUGE_NM;
export const SUIVRE_LOOKAHEAD_H = DEFAULT_ORDERS.budget.hours;
export const SUIVRE_LOOKAHEAD_MAX_NM = DEFAULT_ORDERS.budget.maxNm;
/** Simulation: the whole leg — 12 nm near the boat, then SIM_FAR_STEP_NM. */
export const MAX_PEARLS_SIM = 200;
export const SIM_NEAR_NM = 240;
export const SIM_FAR_STEP_NM = 48;
export const MAX_PEARLS_SUIVRE = DEFAULT_ORDERS.budget.maxPearls;
export const DEFAULT_KNOTS = DEFAULT_ORDERS.budget.planningKn;

/** Flatten a drawn FeatureCollection so along-pearls follow that track, not Berry. */
export function flatFromCustomRoute(customRoute) {
  if (!customRoute?.features?.length) return null;
  const flat = flattenRoute(featuresToSegments(customRoute));
  return flat?.points?.length ? flat : null;
}

export function pearlKey(lat, lon, month) {
  const la = Number(lat);
  const lo = Number(lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return "";
  return `${la.toFixed(2)}:${lo.toFixed(2)}:${month ?? ""}`;
}

/** Suivre: hours × planning knots from the orders (Cruise if none). Simulation: whole leg. */
export function lookaheadNmFor(mode, orders = null) {
  if (mode === "suivre") return lookaheadBudget(orders).maxNm;
  return Infinity;
}

/** Suivre: pearls follow the horizon (ceil(nm / 12)). Simulation: fixed engine cap. */
export function maxPearlsFor(mode, orders = null) {
  if (mode === "suivre") return lookaheadBudget(orders).maxPearls;
  return MAX_PEARLS_SIM;
}

export function filmCumAtNm(flat, nm) {
  const pts = flat?.points || [];
  if (!pts.length) return Number(nm) || 0;
  const target = Number(nm) || 0;
  if (pts.length === 1) return pts[0].filmCum ?? pts[0].cumNm ?? 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (b.cumNm < target) continue;
    if (b.jump) return b.filmCum ?? b.cumNm;
    const span = b.cumNm - a.cumNm;
    const t = span > 0 ? (target - a.cumNm) / span : 1;
    const fa = a.filmCum ?? a.cumNm;
    const fb = b.filmCum ?? b.cumNm;
    return fa + t * (fb - fa);
  }
  return pts[pts.length - 1].filmCum ?? pts[pts.length - 1].cumNm ?? target;
}

/**
 * Sample THIS leg ahead of the boat. Skip air hops / non-maritime.
 */
export function sampleLeg(flat, {
  fromNm = 0,
  toNm = Infinity,
  boatNm = 0,
  sampleNm = ROUTE_SAMPLE_NM,
  maxPearls = MAX_PEARLS_SIM,
  lookaheadNm = Infinity,
  month = null,
  /** Pearls kept just behind the boat (the one it just passed): a live thin bag at any film speed. */
  behindNm = 0,
  /** Beyond `nearNm` ahead of the boat, pearls thin out to `farStepNm` (whole leg, bounded). */
  nearNm = Infinity,
  farStepNm = null,
} = {}) {
  const boat = Number(boatNm) || 0;
  const start = Math.max(Number(fromNm) || 0, boat - (Number(behindNm) || 0), 0);
  const cap = Number.isFinite(lookaheadNm) ? start + lookaheadNm : Infinity;
  const end = Math.min(
    Number.isFinite(toNm) ? toNm : Infinity,
    cap,
    flat?.totalNm ?? Infinity,
  );
  const step = Number(sampleNm) > 0 ? sampleNm : ROUTE_SAMPLE_NM;
  const far = Number(farStepNm) > step ? Number(farStepNm) : step;
  const max = Math.max(1, maxPearls);
  const pearls = [];
  if (!flat?.points?.length || end < start) return pearls;
  for (let nm = start; nm <= end + 1e-6 && pearls.length < max; nm += (nm - boat >= nearNm ? far : step)) {
    const hit = interpolateAtNm(flat, nm);
    if (!hit || hit.jump || hit.nonMaritime) continue;
    pearls.push({
      lat: hit.lat,
      lon: hit.lon,
      cumNm: nm,
      filmCum: filmCumAtNm(flat, nm),
      whenNm: nm - boat,
      month,
    });
  }
  return pearls;
}

/**
 * Window of canonical pearls (server `GET /ici/pearls`, 12 nm apart along the
 * official route) around the boat: the two just behind, then all of them for
 * `nearCount`, then one in `farEvery` up to `maxPearls`. Same positions as the
 * server's warmer → the thin bags hit its cache.
 *
 * Each pearl gets `cumNm` / `filmCum` on THIS flat route (nearestNm), so the
 * lookahead detectors read `whenNm` exactly as with `sampleLeg`.
 */
export function canonicalWindow(canonical, flat, {
  boatNm = 0,
  boatLat = null,
  boatLon = null,
  toNm = Infinity,
  maxPearls = MAX_PEARLS_SIM,
  behind = 2,
  nearCount = 20,
  farEvery = 4,
  lookaheadNm = Infinity,
  month = null,
} = {}) {
  const list = Array.isArray(canonical) ? canonical : [];
  if (!list.length || !flat?.points?.length) return [];
  let at = 0;
  if (Number.isFinite(boatLat) && Number.isFinite(boatLon)) {
    let best = Infinity;
    for (let i = 0; i < list.length; i++) {
      const d = haversineNm(list[i][0], list[i][1], boatLat, boatLon);
      if (d < best) {
        best = d;
        at = i;
      }
    }
  }
  const boat = Number(boatNm) || 0;
  const out = [];
  const cap = Number.isFinite(lookaheadNm) ? boat + lookaheadNm : Infinity;
  const end = Math.min(Number.isFinite(toNm) ? toNm : Infinity, cap, flat.totalNm ?? Infinity);
  for (let i = Math.max(0, at - behind); i < list.length && out.length < maxPearls; i++) {
    const ahead = i - at;
    if (ahead > nearCount && (ahead - nearCount) % farEvery !== 0) continue;
    const [lat, lon] = list[i];
    const cumNm = nearestNm(flat, lat, lon);
    if (!Number.isFinite(cumNm)) continue;
    if (cumNm > end + 0.5) break;
    if (ahead > 0 && cumNm + 0.5 < boat) continue; // the route loops back: not ahead on this leg
    out.push({
      lat,
      lon,
      cumNm,
      filmCum: filmCumAtNm(flat, cumNm),
      whenNm: cumNm - boat,
      month,
      canonical: true,
    });
  }
  return out;
}

/**
 * The thin bag of the pearl nearest to the boat (≤ maxNm), re-centred on the
 * boat. While the full bag is still on its way (or already far behind in a
 * fast film), this is what the detectors and the briefing read.
 */
export function nearestPearlBag(pearls, bagMap, boat, { maxNm = 15, month = null } = {}) {
  if (!boat || !Number.isFinite(boat.lat) || !Number.isFinite(boat.lon)) return null;
  const map = bagMap instanceof Map ? bagMap : new Map(Object.entries(bagMap || {}));
  let best = null;
  let bestD = Infinity;
  for (const p of pearls || []) {
    const bag = map.get(pearlKey(p.lat, p.lon, month ?? p.month));
    if (!bag) continue;
    const d = haversineNm(p.lat, p.lon, boat.lat, boat.lon);
    if (d < bestD) {
      bestD = d;
      best = { pearl: p, bag };
    }
  }
  if (!best || bestD > maxNm) return null;
  return {
    ...best.bag,
    at: { lat: boat.lat, lon: boat.lon },
    // `pearl` = what the server collected ("rich": every timeless layer; "thin": ZEE, PoE, MPA, harbours).
    pearl: best.bag.pearl === "rich" ? "rich" : "thin",
    thin: best.bag.pearl !== "rich",
    pearlNm: Math.round(bestD * 10) / 10,
    pearlCumNm: best.pearl.cumNm,
    pearlFilmCum: best.pearl.filmCum,
  };
}

export function attachBags(pearls, bagMap, month, orders = null) {
  const map = bagMap instanceof Map ? bagMap : new Map(Object.entries(bagMap || {}));
  const T = thresholdValues(orders);
  return (pearls || []).map((p) => {
    const bag = map.get(pearlKey(p.lat, p.lon, month ?? p.month))
      || map.get(pearlKey(p.lat, p.lon, p.month))
      || null;
    const amp = (bag?.amp || []).filter((a) => !Number.isFinite(a.nm) || a.nm <= T.alongAmpNm);
    const harbours = [
      ...(bag?.nearby?.marinas || []),
      ...(bag?.nearby?.capitaineries || []),
      ...(bag?.nearby?.wpi || []),
    ].filter((h) => Number.isFinite(h?.nm) && h.nm < T.marinaRefugeNm && h.name);
    return {
      ...p,
      zee: bag?.zee ?? null,
      poe: bag?.poe || [],
      amp,
      harbours,
    };
  });
}

export function alongHarbours(pearls) {
  const list = [];
  for (const p of pearls || []) {
    for (const h of p.harbours || []) {
      list.push({
        ...h,
        nm: (p.whenNm ?? 0) + (Number(h.nm) || 0),
        along: true,
      });
    }
  }
  list.sort((a, b) => a.nm - b.nm);
  return list;
}

export function buildAlongIndex(pearls, bagMap, month, orders = null) {
  const decorated = attachBags(pearls, bagMap, month, orders);
  return {
    pearls: decorated,
    harbours: alongHarbours(decorated),
  };
}

/** Simulation: all visible on this leg. Suivre: live + one upcoming. */
export function filmEventMarks(events, { mode = "simulation" } = {}) {
  const visible = (events || []).filter((e) => (
    e && e.judge !== "hide" && e.type !== "group" && Number.isFinite(e.filmCum)
  ));
  if (mode !== "suivre") return visible;
  const nows = visible.filter((e) => e.judge === "now");
  const later = visible
    .filter((e) => e.judge === "later" || e.judge === "group")
    .sort((a, b) => (a.whenNm ?? 0) - (b.whenNm ?? 0));
  const out = [];
  if (nows.length) out.push(nows[nows.length - 1]);
  if (later[0]) out.push(later[0]);
  return out;
}

export function upsertLedger(ledger, incoming) {
  const out = [...(ledger || [])];
  for (const ev of incoming || []) {
    if (!ev || ev.judge === "hide") continue;
    const key = ev.stableKey || ev.id;
    const idx = out.findIndex((x) => (x.stableKey || x.id) === key);
    if (idx >= 0) {
      const prev = out[idx];
      const next = { ...prev, ...ev };
      const keepStory = prev.story
        && (prev.story.status === "pending" || prev.story.status === "ready")
        && (!ev.story || ev.story.status === "template");
      if (keepStory) {
        // The story was written under the orders of that time: keep them together.
        next.story = prev.story;
        if (prev.skipper) next.skipper = prev.skipper;
        if (prev.filmPhrase && !next.filmPhrase) next.filmPhrase = prev.filmPhrase;
      }
      out[idx] = next;
    } else out.push(ev);
  }
  return out;
}

export function promoteLaterAtPlayhead(ledger, filmCum) {
  if (!Number.isFinite(filmCum)) return ledger || [];
  return (ledger || []).map((ev) => {
    if (ev.judge !== "later" || ev.promoted || ev.seenNow) return ev;
    if (!Number.isFinite(ev.filmCum) || filmCum + 0.5 < ev.filmCum) return ev;
    return { ...ev, judge: "now", promoted: true, seenNow: true, judgeReason: "playhead" };
  });
}
