/**
 * Display judge — hide | now | later | group.
 * Rules only. Not Nemotron Ultra. No HTTP. No chat.
 * Hs alert and grouping window come from `ctx.orders` (Cruise when absent).
 * Already judged pastilles are never re-judged here: only the next events read new orders.
 */

import { thresholdValues } from "./skipperOrders.js";

export const JUDGE_HIDE = "hide";
export const JUDGE_NOW = "now";
export const JUDGE_LATER = "later";
export const JUDGE_GROUP = "group";

const NOW_TYPES = new Set([
  "zee-enter",
  "cyclone-nearby",
  "marina-refuge",
  "depth-alert",
  "cable-alert",
  "wind-gale",
  "escale-in",
  "escale-out",
  "air-hop",
]);

const HIDE_TYPES = new Set([
  "review-admin",
  "grib-absent",
]);

const CINEMA_HIDE = new Set([
  "science-hit",
  "aton-nearby",
  "project-nearby",
]);

const NEVER_GROUP = new Set([
  "marina-refuge",
  "cyclone-nearby",
  "depth-alert",
  "wind-gale",
]);

const FORMALITY = new Set([
  "zee-enter",
  "zee-ahead",
  "zee-exit",
  "poe-ahead",
  "amp-ahead",
  "amp-enter",
]);

const METEO_SOFT = new Set([
  "wind-shift",
  "current-shift",
  "hs-shift",
]);

function isSevereWx(ev, T) {
  const p = ev?.payload || {};
  return ev?.type === "wx-alert" && Boolean(
    p.severe || p.rain || p.gale || (Number.isFinite(p.hs) && p.hs >= T.hsAlertM),
  );
}

function isImmediate(ev, T) {
  if (NOW_TYPES.has(ev.type)) return true;
  if (isSevereWx(ev, T)) return true;
  if (ev.type === "amp-enter" && ev.payload?.visitable) return true;
  if (ev.type === "hs-shift" && (ev.payload?.alert || ev.payload?.hs >= T.hsAlertM)) return true;
  if (ev.type === "wind-shift" && ev.payload?.chainedGale) return true;
  return false;
}

function hideReason(ev, ctx) {
  if (HIDE_TYPES.has(ev.type)) {
    return ev.type === "grib-absent" ? "grib-hud" : ev.type;
  }
  if (ctx.cinema && CINEMA_HIDE.has(ev.type)) return "cinema";
  if (ev.duplicate) return "duplicate";
  return null;
}

function familyOf(type) {
  if (FORMALITY.has(type)) return "formality";
  if (METEO_SOFT.has(type)) return "meteo";
  return "other";
}

function clusterByNm(events, windowNm) {
  const sorted = [...events].sort((a, b) => (a.whenNm ?? 0) - (b.whenNm ?? 0));
  const clusters = [];
  for (const ev of sorted) {
    const last = clusters[clusters.length - 1];
    if (!last) {
      clusters.push([ev]);
      continue;
    }
    const anchor = last[0].whenNm ?? 0;
    if (Math.abs((ev.whenNm ?? 0) - anchor) <= windowNm) {
      last.push(ev);
    } else {
      clusters.push([ev]);
    }
  }
  return clusters;
}

function digestPhrase(members) {
  const names = members.map((e) => e.type).join(" + ");
  return {
    fr: `Depuis cette jambe : ${names}.`,
    en: `Along this leg: ${names}.`,
  };
}

export function makeDigest(members, ctx = {}) {
  const first = members[0];
  const types = members.map((e) => e.type);
  return {
    id: `group:${first?.id || types.join("+")}`,
    type: "group",
    severity: members.some((e) => e.severity === "alert") ? "alert" : "watch",
    whenNm: first?.whenNm ?? 0,
    filmCum: first?.filmCum ?? null,
    legId: first?.legId ?? ctx.legId ?? null,
    phrase: null,
    story: { status: "template" },
    judge: JUDGE_NOW,
    judgeReason: "digest",
    kind: null,
    payload: {
      members: types,
      events: members.map((e) => ({
        id: e.id,
        type: e.type,
        payload: e.payload,
      })),
      tavily: null,
      nvidia: null,
    },
    digest: digestPhrase(members),
  };
}

function shouldGroup(cluster, profile) {
  if (cluster.length < 2) return false;
  if (cluster.length > 3 && profile !== "fast") return false;
  const families = new Set(cluster.map((e) => familyOf(e.type)));
  if (families.size === 1 && (families.has("formality") || families.has("meteo"))) {
    return true;
  }
  if (profile === "fast") return true;
  return false;
}

const BRIEFING_FIRST = [
  "marina-refuge",
  "cyclone-nearby",
  "depth-alert",
  "wind-gale",
  "cable-alert",
  "wx-alert",
];

function pickBriefing(judged) {
  const nows = judged.filter((e) => e.judge === JUDGE_NOW);
  for (const type of BRIEFING_FIRST) {
    const hit = nows.find((e) => e.type === type);
    if (hit) return hit;
  }
  return nows.find((e) => e.type === "group")
    || nows[0]
    || null;
}

/**
 * Decide hide / now / later / group.
 * First question: show at all? Then: now, later alone, or grouped later.
 */
export function judgeEvents(events, ctx = {}) {
  const profile = ctx.profile || "normal";
  const T = thresholdValues(ctx.orders);
  const windowNm = profile === "fast" ? T.groupNmFast : T.groupNm;
  const judged = [];
  const visible = [];
  const seenIds = ctx.seenIds instanceof Set ? ctx.seenIds : new Set(ctx.seenIds || []);

  for (const ev of events || []) {
    if (seenIds.has(ev.id)) {
      judged.push({ ...ev, judge: JUDGE_HIDE, judgeReason: "duplicate" });
      continue;
    }
    const hide = hideReason(ev, ctx);
    if (hide) {
      judged.push({ ...ev, judge: JUDGE_HIDE, judgeReason: hide });
      continue;
    }
    visible.push(ev);
  }

  const locked = [];
  const candidates = [];
  for (const ev of visible) {
    if (ctx.skipperClickId && (ctx.skipperClickId === ev.id || ctx.skipperClickId === ev.stableKey)) {
      locked.push({ ...ev, judge: JUDGE_NOW, judgeReason: "skipper-click" });
      continue;
    }
    if (NEVER_GROUP.has(ev.type)) {
      locked.push({ ...ev, judge: JUDGE_NOW, judgeReason: "safety" });
      continue;
    }
    if (isSevereWx(ev, T)) {
      locked.push({ ...ev, judge: JUDGE_NOW, judgeReason: "safety" });
      continue;
    }
    candidates.push(ev);
  }

  judged.push(...locked);

  const byFamily = new Map();
  for (const ev of candidates) {
    const fam = familyOf(ev.type);
    if (!byFamily.has(fam)) byFamily.set(fam, []);
    byFamily.get(fam).push(ev);
  }

  let digest = null;
  for (const [, list] of byFamily) {
    const clusters = clusterByNm(list, windowNm);
    for (const cluster of clusters) {
      if (shouldGroup(cluster, profile)) {
        for (const ev of cluster) {
          judged.push({ ...ev, judge: JUDGE_GROUP, judgeReason: "window" });
        }
        const d = makeDigest(cluster, ctx);
        judged.push(d);
        if (!digest) digest = d;
      } else {
        for (const ev of cluster) {
          const now = isImmediate(ev, T);
          judged.push({
            ...ev,
            judge: now ? JUDGE_NOW : JUDGE_LATER,
            judgeReason: now ? "safety" : "later",
          });
        }
      }
    }
  }

  const briefing = pickBriefing(judged);
  return { judged, briefing, digest };
}

export function judgeEvent(event, ctx = {}) {
  const { judged } = judgeEvents(event ? [event] : [], ctx);
  return judged[0] || null;
}
