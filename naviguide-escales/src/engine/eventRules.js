/**
 * Event detectors for the ici() bag.
 * Pure functions: at + prev + along + ctx + memory → EventRecord[].
 * No HTTP. No chat. No Tavily / NVIDIA.
 *
 * Thresholds come from `ctx.orders` (skipper orders, S2). The `export const`
 * below stay the Cruise defaults — used when no orders are passed.
 */

import { skipperSnapshot, thresholdValues } from "./skipperOrders.js";

export const ROUTE_SAMPLE_NM = 12;
export const WIND_SHIFT_KT = 8;
export const WIND_SHIFT_DEG = 40;
export const WIND_SHIFT_RESET_KT = 4;
export const WIND_SHIFT_RESET_DEG = 20;
export const COOLDOWN_NM = 15;
export const COOLDOWN_MIN = 30;
export const GALE_KT = 34;
export const GALE_HOLD_KT = 28;
export const GALE_PCT = 15;
export const CURRENT_SHIFT_KN = 1.0;
export const CURRENT_IGNORE_KN = 0.3;
export const CURRENT_INVERT_DEG = 120;
export const HS_SHIFT_M = 1.0;
export const HS_ALERT_M = 3.5;
export const AMP_HYSTERESIS_NM = 5;
export const AMP_AHEAD_MIN_NM = 5;
export const RAIN_MM_H = 4;
export const RAIN_3H_MM = 10;
export const MARINA_REFUGE_NM = 25;
export const MARINA_REFUGE_COOLDOWN_MIN = 360;
export const DEPTH_ALERT_M = 15;
export const DEPTH_COOLDOWN_NM = 2;
export const GROUP_NM = 15;
export const GROUP_NM_FAST = 80;
export const GROUP_WALL_MS = 8000;

export const E1_TYPES = Object.freeze([
  "zee-enter",
  "zee-exit",
  "wind-shift",
  "wind-gale",
  "current-shift",
  "hs-shift",
  "amp-enter",
  "wx-alert",
  "marina-refuge",
  "depth-alert",
]);

export const RESERVED_TYPES = Object.freeze([
  "zee-ahead",
  "poe-ahead",
  "amp-ahead",
  "cyclone-nearby",
  "science-hit",
  "escale-in",
  "escale-out",
  "grib-absent",
  "satellite-scene",
  "review-admin",
  "aton-nearby",
  "anchorage-ahead",
  "project-nearby",
  "cable-alert",
  "air-hop",
]);

const EXIT_KEY = "exit:high-seas";

export function emptyEventMemory(legId = null) {
  return {
    legId,
    seq: 0,
    seenZee: new Set(),
    zeeCandidate: null,
    seenAmp: new Set(),
    ampPending: new Map(),
    baselineAmp: new Set(),
    lastAmpIds: new Set(),
    windBaseline: null,
    windShiftOpen: false,
    lastWindShiftNm: null,
    lastWindShiftMin: null,
    galeHold: false,
    currentBaseline: null,
    lastCurrentNm: null,
    lastCurrentMin: null,
    hsBaseline: null,
    lastHsNm: null,
    lastHsMin: null,
    lastWxKey: null,
    lastWxNm: null,
    lastWxMin: null,
    lastMarinaKey: null,
    lastMarinaMin: null,
    lastDepthNm: null,
    seenZeeAhead: new Set(),
    seenAmpAhead: new Set(),
    seenPoeAhead: new Set(),
  };
}

export function smallestAngleDeg(a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  let d = Math.abs(a - b) % 360;
  if (d > 180) d = 360 - d;
  return d;
}

export function sumRainHours(samples, iso, hours = 3) {
  if (!Array.isArray(samples) || !samples.length) return null;
  const t0 = iso ? Date.parse(iso) : NaN;
  const origin = Number.isFinite(t0) ? t0 : Date.parse(samples[0]?.t || samples[0]?.iso || "");
  if (!Number.isFinite(origin)) return null;
  let sum = 0;
  let n = 0;
  for (const row of samples) {
    const t = Date.parse(row?.t || row?.iso || "");
    if (!Number.isFinite(t)) continue;
    const dtH = (t - origin) / 3_600_000;
    if (dtH < -0.5 || dtH > hours) continue;
    if (!Number.isFinite(row.rainMm)) continue;
    sum += row.rainMm;
    n += 1;
  }
  return n ? Math.round(sum * 100) / 100 : null;
}

function honest(extra = {}) {
  return {
    tavily: null,
    nvidia: null,
    ...extra,
  };
}

function nextId(memory, type, key) {
  memory.seq += 1;
  const bit = key == null || key === "" ? "x" : String(key);
  return `${type}:${bit}:${memory.seq}`;
}

function makeEvent(memory, type, {
  key,
  severity = "info",
  whenNm = 0,
  filmCum = null,
  legId = null,
  kind = null,
  payload = {},
  name = null,
} = {}) {
  const bit = key == null || key === "" ? "x" : String(key);
  return {
    id: nextId(memory, type, key),
    stableKey: `${type}:${bit}`,
    type,
    severity,
    whenNm,
    filmCum,
    legId,
    name,
    phrase: null,
    story: { status: "template" },
    judge: null,
    kind,
    payload: honest(payload),
  };
}

function ensureMemory(memory, legId) {
  const mem = memory || emptyEventMemory(legId);
  if (legId && mem.legId && mem.legId !== legId) {
    return emptyEventMemory(legId);
  }
  if (legId && !mem.legId) mem.legId = legId;
  return mem;
}

function cooledDown(lastNm, lastMin, ctx, nmLimitArg = null, minLimitArg = null) {
  const nmLimit = nmLimitArg ?? ctx.T?.cooldownNm ?? COOLDOWN_NM;
  const minLimit = minLimitArg ?? ctx.T?.cooldownMin ?? COOLDOWN_MIN;
  if (lastNm == null && lastMin == null) return true;
  const dNm = Number.isFinite(lastNm) && Number.isFinite(ctx.cumNm)
    ? ctx.cumNm - lastNm
    : null;
  const dMin = Number.isFinite(lastMin) && Number.isFinite(ctx.clockMin)
    ? ctx.clockMin - lastMin
    : null;
  if (dNm == null && dMin == null) return false;
  if (dNm != null && dNm >= nmLimit) return true;
  if (dMin != null && dMin >= minLimit) return true;
  return false;
}

function ampId(amp) {
  return amp?.site_id ?? amp?.id ?? amp?.wdpaid ?? amp?.name ?? null;
}

function isVisitableAmp(amp) {
  return Boolean(amp?.visit_url && amp.visit_url !== amp.manager_url);
}

export function nearestHarbour(dossier, along, maxNm = MARINA_REFUGE_NM) {
  const alongList = along?.harbours || along?.marinas || [];
  const nearby = [
    ...(dossier?.nearby?.marinas || []),
    ...(dossier?.nearby?.capitaineries || []),
    ...(dossier?.nearby?.wpi || []),
  ];
  const pool = (alongList.length ? alongList : nearby)
    .filter((h) => Number.isFinite(h?.nm) && h.nm < maxNm && h.name);
  pool.sort((a, b) => a.nm - b.nm);
  return pool[0] || null;
}

export function readWind(at, ctx = {}) {
  if (ctx.mode === "suivre") {
    const w = at?.weather?.wind;
    if (at?.weather?.kind === "forecast" && w && Number.isFinite(w.speedKnots)) {
      return {
        tws: w.speedKnots,
        twd: Number.isFinite(w.dirFromDeg) ? w.dirFromDeg : null,
        kind: "forecast",
        galePct: null,
        source: at.weather.model || at.weather.source || "GFS",
      };
    }
    const g = ctx.gribWind;
    if (g && Number.isFinite(g.windKnots)) {
      return {
        tws: g.windKnots,
        twd: Number.isFinite(g.dirFromDeg) ? g.dirFromDeg : null,
        kind: "forecast",
        galePct: null,
        source: g.model || "GFS",
      };
    }
    return null;
  }
  const c = at?.climatology;
  if (!c) return null;
  const most = c.point?.wind_atlas?.most_likely || c.point?.wind_atlas?.vector_mean;
  const zone = c.wind;
  const tws = most?.speed_knots ?? zone?.speedKnots;
  const twd = most?.dir_deg ?? zone?.dirFromDeg;
  if (!Number.isFinite(tws)) return null;
  const galePct = c.rose?.gale_pct ?? c.point?.wind_atlas?.gale_pct ?? c.point?.gale_pct;
  return {
    tws,
    twd: Number.isFinite(twd) ? twd : null,
    kind: "climatology",
    galePct: Number.isFinite(galePct) ? galePct : null,
    source: c.source || "atlas",
  };
}

function readCurrent(at, ctx = {}) {
  if (ctx.mode === "suivre") {
    const c = at?.weather?.current;
    if (at?.weather?.kind === "forecast" && c && Number.isFinite(c.speedKnots)) {
      return {
        kn: c.speedKnots,
        dir: Number.isFinite(c.dirToDeg) ? c.dirToDeg : null,
        kind: "forecast",
        source: c.source || "RTOFS",
      };
    }
    return null;
  }
  const c = at?.climatology?.point?.current || at?.climatology?.current;
  const kn = c?.speed_knots ?? c?.speedKnots;
  const dir = c?.direction_to_deg ?? c?.dirToDeg;
  if (!Number.isFinite(kn)) return null;
  return {
    kn,
    dir: Number.isFinite(dir) ? dir : null,
    kind: "climatology",
    source: at?.climatology?.source || "atlas",
  };
}

export function readHs(at, ctx = {}) {
  if (ctx.mode === "suivre") {
    const hs = at?.weather?.wave?.hs ?? ctx.gribWind?.hs;
    if (!Number.isFinite(hs)) return null;
    return { hs, kind: "forecast", source: at?.weather?.model || "GFS-Wave" };
  }
  const w = at?.climatology?.point?.wave || at?.climatology?.wave;
  const p50 = w?.hs_p50_m;
  const p90 = w?.hs_p90_m;
  const hs = Number.isFinite(p50) ? p50 : p90;
  if (!Number.isFinite(hs)) return null;
  return {
    hs,
    p50: Number.isFinite(p50) ? p50 : null,
    p90: Number.isFinite(p90) ? p90 : null,
    kind: "climatology",
    source: at?.climatology?.source || "atlas",
  };
}

function rainIntense(ctx) {
  if (ctx.mode !== "suivre") return null;
  const T = ctx.T || thresholdValues(null);
  const hour = ctx.rainMm;
  const sum3 = ctx.rain3hMm;
  if (Number.isFinite(hour) && hour >= T.rainMmH) {
    return { rainMm: hour, rain3hMm: Number.isFinite(sum3) ? sum3 : null };
  }
  if (Number.isFinite(sum3) && sum3 >= T.rain3hMm) {
    return { rainMm: Number.isFinite(hour) ? hour : null, rain3hMm: sum3 };
  }
  return null;
}

function detectZee(at, prev, memory, ctx, events) {
  const mrgid = at?.zee?.mrgid ?? null;
  if (prev === undefined) {
    memory.zeeCandidate = null;
    return;
  }
  const prevMrgid = prev?.zee?.mrgid ?? null;

  if (mrgid === prevMrgid) {
    if (mrgid != null && memory.zeeCandidate?.mrgid === mrgid) {
      memory.zeeCandidate.count += 1;
      if (memory.zeeCandidate.count >= 2 && !memory.seenZee.has(mrgid)) {
        memory.seenZee.add(mrgid);
        memory.seenZee.delete(EXIT_KEY);
        events.push(makeEvent(memory, "zee-enter", {
          key: mrgid,
          severity: "watch",
          whenNm: 0,
          filmCum: ctx.filmCum ?? null,
          legId: ctx.legId,
          name: at?.zee?.name || memory.zeeCandidate.name,
          payload: {
            zee: {
              name: at?.zee?.name || null,
              mrgid,
              gold_pack: Boolean(at?.zee?.gold),
            },
            poe: (at?.poe || []).slice(0, 4).map((p) => ({
              name: p.name,
              nm: p.nm ?? null,
              url: p.url || null,
            })),
            weather: null,
            weather_reason: "not_in_this_event",
            rain: null,
            rain_reason: "not_in_this_event",
          },
        }));
        memory.zeeCandidate = null;
      }
    }
    return;
  }

  if (mrgid == null) {
    memory.zeeCandidate = null;
    if (!memory.seenZee.has(EXIT_KEY)) {
      memory.seenZee.add(EXIT_KEY);
      events.push(makeEvent(memory, "zee-exit", {
        key: "high-seas",
        severity: "info",
        whenNm: 0,
        filmCum: ctx.filmCum ?? null,
        legId: ctx.legId,
        payload: {
          zee: null,
          weather: null,
          weather_reason: "not_in_this_event",
        },
      }));
    }
    return;
  }

  if (memory.seenZee.has(mrgid)) {
    memory.zeeCandidate = null;
    return;
  }
  memory.zeeCandidate = { mrgid, count: 1, name: at?.zee?.name || null };
}

function detectAmp(at, prev, memory, ctx, events) {
  const nowList = at?.amp || [];
  const nowIds = new Set(nowList.map(ampId).filter(Boolean));
  if (prev === undefined) {
    memory.baselineAmp = nowIds;
    memory.lastAmpIds = nowIds;
    return;
  }
  for (const id of [...memory.ampPending.keys()]) {
    if (!nowIds.has(id)) memory.ampPending.delete(id);
  }
  for (const amp of nowList) {
    const id = ampId(amp);
    if (!id || memory.seenAmp.has(id)) continue;
    if (memory.baselineAmp.has(id)) continue;
    if (!memory.ampPending.has(id)) {
      memory.ampPending.set(id, Number.isFinite(ctx.cumNm) ? ctx.cumNm : 0);
      continue;
    }
    memory.ampPending.delete(id);
    memory.seenAmp.add(id);
    memory.baselineAmp.add(id);
    const visitable = isVisitableAmp(amp);
    events.push(makeEvent(memory, "amp-enter", {
      key: id,
      severity: visitable ? "watch" : "info",
      whenNm: 0,
      filmCum: ctx.filmCum ?? null,
      legId: ctx.legId,
      name: amp.name || id,
        payload: {
          amp: {
            name: amp.name || id,
            site_id: id,
            nm: amp.nm ?? null,
            visit_url: amp.visit_url || null,
            manager_url: amp.manager_url || null,
            visitable,
            entry: amp.entry ?? null,
            speed: amp.speed ?? null,
            traffic: amp.traffic || null,
            inside: Boolean(amp.inside),
          },
          visitable,
          inside: Boolean(amp.inside),
          weather: null,
          weather_reason: "not_in_this_event",
        },
    }));
  }
  memory.lastAmpIds = nowIds;
}

function detectWind(at, memory, ctx, events) {
  const sample = readWind(at, ctx);
  if (!sample) return;
  const T = ctx.T;

  const galeNow = sample.tws >= T.galeKt
    || (sample.galePct != null && sample.galePct >= T.galePct);
  if (galeNow && !memory.galeHold) {
    memory.galeHold = true;
    events.push(makeEvent(memory, "wind-gale", {
      key: sample.kind,
      severity: "alert",
      whenNm: 0,
      filmCum: ctx.filmCum ?? null,
      legId: ctx.legId,
      kind: sample.kind,
      payload: {
        tws: sample.tws,
        twd: sample.twd,
        galePct: sample.galePct,
        kind: sample.kind,
        source: sample.source,
      },
    }));
  }
  if (memory.galeHold && sample.tws < T.galeHoldKt
    && !(sample.galePct != null && sample.galePct >= T.galePct)) {
    memory.galeHold = false;
  }

  if (!memory.windBaseline) {
    memory.windBaseline = sample;
    return;
  }
  if (memory.windBaseline.kind !== sample.kind) {
    memory.windBaseline = sample;
    memory.windShiftOpen = false;
    return;
  }

  const dTws = Math.round((sample.tws - memory.windBaseline.tws) * 10) / 10;
  const dTwd = smallestAngleDeg(sample.twd, memory.windBaseline.twd);
  const absTws = Math.abs(dTws);

  if (memory.windShiftOpen) {
    if (absTws < T.windShiftResetKt && (dTwd == null || dTwd < T.windShiftResetDeg)) {
      memory.windShiftOpen = false;
      memory.windBaseline = sample;
    }
    return;
  }

  const shifted = absTws >= T.windShiftKt || (dTwd != null && dTwd >= T.windShiftDeg);
  if (!shifted) return;
  if (!cooledDown(memory.lastWindShiftNm, memory.lastWindShiftMin, ctx)) return;

  memory.windShiftOpen = true;
  memory.lastWindShiftNm = ctx.cumNm ?? null;
  memory.lastWindShiftMin = ctx.clockMin ?? null;
  events.push(makeEvent(memory, "wind-shift", {
    key: sample.kind,
    severity: memory.galeHold ? "watch" : "info",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    kind: sample.kind,
    payload: {
      tws: sample.tws,
      twd: sample.twd,
      dTws,
      dTwd,
      kind: sample.kind,
      source: sample.source,
      chainedGale: Boolean(memory.galeHold),
    },
  }));
}

function detectCurrent(at, memory, ctx, events) {
  const sample = readCurrent(at, ctx);
  if (!sample) return;
  if (!memory.currentBaseline) {
    memory.currentBaseline = sample;
    return;
  }
  if (memory.currentBaseline.kind !== sample.kind) {
    memory.currentBaseline = sample;
    return;
  }
  const prev = memory.currentBaseline;
  const T = ctx.T;
  if (prev.kn < T.currentIgnoreKn && sample.kn < T.currentIgnoreKn) {
    memory.currentBaseline = sample;
    return;
  }
  const dKn = Math.round((sample.kn - prev.kn) * 10) / 10;
  const dDir = smallestAngleDeg(sample.dir, prev.dir);
  const invert = dDir != null && dDir >= T.currentInvertDeg;
  if (Math.abs(dKn) < T.currentShiftKn && !invert) return;
  if (!cooledDown(memory.lastCurrentNm, memory.lastCurrentMin, ctx)) return;
  memory.lastCurrentNm = ctx.cumNm ?? null;
  memory.lastCurrentMin = ctx.clockMin ?? null;
  memory.currentBaseline = sample;
  events.push(makeEvent(memory, "current-shift", {
    key: sample.kind,
    severity: "info",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    kind: sample.kind,
    payload: {
      kn: sample.kn,
      dir: sample.dir,
      dKn,
      dDir,
      invert,
      kind: sample.kind,
      source: sample.source,
    },
  }));
}

function detectHs(at, memory, ctx, events) {
  const sample = readHs(at, ctx);
  if (!sample) return;
  if (!memory.hsBaseline) {
    memory.hsBaseline = sample;
    return;
  }
  if (memory.hsBaseline.kind !== sample.kind) {
    memory.hsBaseline = sample;
    return;
  }
  const T = ctx.T;
  const dHs = Math.round((sample.hs - memory.hsBaseline.hs) * 10) / 10;
  const alert = sample.hs >= T.hsAlertM
    || (sample.p90 != null && sample.p90 >= T.hsAlertM);
  if (Math.abs(dHs) < T.hsShiftM && !alert) return;
  if (!cooledDown(memory.lastHsNm, memory.lastHsMin, ctx)) return;
  memory.lastHsNm = ctx.cumNm ?? null;
  memory.lastHsMin = ctx.clockMin ?? null;
  memory.hsBaseline = sample;
  events.push(makeEvent(memory, "hs-shift", {
    key: sample.kind,
    severity: alert ? "alert" : "info",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    kind: sample.kind,
    payload: {
      hs: sample.hs,
      p50: sample.p50 ?? null,
      p90: sample.p90 ?? null,
      dHs,
      kind: sample.kind,
      source: sample.source,
      alert,
      alertM: T.hsAlertM,
    },
  }));
}

function detectWxMarina(at, along, memory, ctx, events) {
  const T = ctx.T;
  const rain = rainIntense(ctx);
  const wind = readWind(at, ctx);
  const hs = readHs(at, ctx);
  const gale = Boolean(
    wind && (wind.tws >= T.galeKt || (wind.galePct != null && wind.galePct >= T.galePct)),
  );
  const hsHi = Boolean(hs && (hs.hs >= T.hsAlertM || (hs.p90 != null && hs.p90 >= T.hsAlertM)));
  if (!rain && !gale && !hsHi) return;

  const key = [rain && "rain", gale && "gale", hsHi && "hs"].filter(Boolean).join("+");
  if (memory.lastWxKey === key
    && !cooledDown(memory.lastWxNm, memory.lastWxMin, ctx)) {
    return;
  }
  memory.lastWxKey = key;
  memory.lastWxNm = ctx.cumNm ?? null;
  memory.lastWxMin = ctx.clockMin ?? null;

  const severe = Boolean(rain || gale || hsHi);
  events.push(makeEvent(memory, "wx-alert", {
    key,
    severity: severe ? "alert" : "watch",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    kind: ctx.mode === "suivre" ? "forecast" : "climatology",
    payload: {
      rain: Boolean(rain),
      rainMm: rain?.rainMm ?? null,
      rain3hMm: rain?.rain3hMm ?? null,
      gale,
      hs: hs?.hs ?? null,
      severe,
      kind: ctx.mode === "suivre" ? "forecast" : "climatology",
      rain_reason: ctx.mode === "simulation"
        ? "simulation_no_rain"
        : (rain ? null : "suivre_grib_absent_or_below_threshold"),
    },
  }));

  if (!rain || ctx.mode !== "suivre") return;
  const port = nearestHarbour(at, along, T.marinaRefugeNm);
  if (!port) return;
  const pkey = port.name;
  if (memory.lastMarinaKey === pkey
    && !cooledDown(null, memory.lastMarinaMin, ctx, Infinity, T.marinaRefugeCooldownMin)) {
    return;
  }
  memory.lastMarinaKey = pkey;
  memory.lastMarinaMin = ctx.clockMin ?? null;
  events.push(makeEvent(memory, "marina-refuge", {
    key: pkey,
    severity: "alert",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    name: port.name,
    payload: {
      harbour: { name: port.name, nm: port.nm, kind: port.kind || "marina" },
      rainMm: rain.rainMm,
      rain3hMm: rain.rain3hMm,
      kind: "forecast",
    },
  }));
}

function detectDepth(at, memory, ctx, events) {
  const T = ctx.T;
  const emod = at?.emodnet?.bathy?.depth_m;
  const gebco = at?.depthOffshore;
  let hit = null;
  if (Number.isFinite(emod) && Math.abs(emod) < T.depthAlertM && Math.abs(emod) >= 1) {
    hit = { m: Math.round(Math.abs(emod) * 10) / 10, source: "emodnet" };
  } else if (Number.isFinite(gebco) && Math.abs(gebco) >= 1 && Math.abs(gebco) < T.depthAlertM) {
    hit = { m: Math.round(Math.abs(gebco) * 10) / 10, source: "gebco" };
  }
  if (!hit) return;
  if (memory.lastDepthNm != null
    && Number.isFinite(ctx.cumNm)
    && ctx.cumNm - memory.lastDepthNm < T.depthCooldownNm) {
    return;
  }
  memory.lastDepthNm = ctx.cumNm ?? 0;
  events.push(makeEvent(memory, "depth-alert", {
    key: hit.source,
    severity: "alert",
    whenNm: 0,
    filmCum: ctx.filmCum ?? null,
    legId: ctx.legId,
    kind: "observation",
    payload: {
      depthM: hit.m,
      source: hit.source,
      kind: "observation",
      alertM: T.depthAlertM,
      label: T.depthLabel,
    },
  }));
}

function detectAhead(at, along, memory, ctx, events) {
  const pearls = along?.pearls || [];
  if (!pearls.length) return;
  const boatMrgid = at?.zee?.mrgid ?? null;

  for (const pearl of pearls) {
    if ((pearl.whenNm ?? 0) < 0.5) continue;
    const mrgid = pearl.zee?.mrgid ?? null;
    if (!mrgid || mrgid === boatMrgid || memory.seenZeeAhead.has(mrgid) || memory.seenZee.has(mrgid)) {
      continue;
    }
    memory.seenZeeAhead.add(mrgid);
    events.push(makeEvent(memory, "zee-ahead", {
      key: mrgid,
      severity: "info",
      whenNm: pearl.whenNm,
      filmCum: pearl.filmCum ?? null,
      legId: ctx.legId,
      name: pearl.zee?.name || null,
      payload: {
        zee: { name: pearl.zee?.name || null, mrgid, gold_pack: Boolean(pearl.zee?.gold) },
        whenNm: pearl.whenNm,
        weather: null,
        weather_reason: "not_in_this_event",
      },
    }));
  }

  for (const pearl of pearls) {
    if ((pearl.whenNm ?? 0) < ctx.T.ampAheadMinNm) continue;
    for (const amp of pearl.amp || []) {
      const id = amp.site_id ?? amp.id ?? amp.wdpaid ?? amp.name;
      if (!id || memory.seenAmpAhead.has(id) || memory.seenAmp.has(id)) continue;
      memory.seenAmpAhead.add(id);
      const visitable = Boolean(amp.visit_url && amp.visit_url !== amp.manager_url);
      events.push(makeEvent(memory, "amp-ahead", {
        key: id,
        severity: visitable ? "watch" : "info",
        whenNm: pearl.whenNm,
        filmCum: pearl.filmCum ?? null,
        legId: ctx.legId,
        name: amp.name || id,
        payload: {
          amp: {
            name: amp.name || id,
            site_id: id,
            visit_url: amp.visit_url || null,
            visitable,
            entry: amp.entry ?? null,
            speed: amp.speed ?? null,
            traffic: amp.traffic || null,
            inside: Boolean(amp.inside),
          },
          visitable,
          whenNm: pearl.whenNm,
        },
      }));
    }
  }

  for (const pearl of pearls) {
    if ((pearl.whenNm ?? 0) < 0.5) continue;
    const poe = (pearl.poe || [])[0];
    if (!poe?.name) continue;
    const key = `${pearl.zee?.mrgid || boatMrgid || "x"}:${poe.name}`;
    if (memory.seenPoeAhead.has(key)) continue;
    memory.seenPoeAhead.add(key);
    events.push(makeEvent(memory, "poe-ahead", {
      key,
      severity: "info",
      whenNm: pearl.whenNm ?? poe.nm ?? 0,
      filmCum: pearl.filmCum ?? ctx.filmCum ?? null,
      legId: ctx.legId,
      name: poe.name,
      payload: {
        poe: { name: poe.name, nm: poe.nm ?? pearl.whenNm ?? null, url: poe.url || null },
        zee: { mrgid: pearl.zee?.mrgid || boatMrgid },
      },
    }));
    break;
  }
}

/**
 * Detect E1 events + E2 ahead (if `along` pearls are ready).
 * First bag (`prev === undefined`) never emits zee-enter / amp-enter.
 * `ctx.orders` (resolved skipper orders) sets every threshold; Cruise when absent.
 * Each event carries a frozen `skipper` snapshot: the orders that made IT switch.
 */
export function detectEvents({
  at,
  prev,
  along = null,
  ctx = {},
  memory,
} = {}) {
  const mem = ensureMemory(memory, ctx.legId);
  if (ctx.airHop) {
    return { events: [], memory: mem };
  }
  const c = { ...ctx, T: thresholdValues(ctx.orders) };
  const events = [];
  detectZee(at, prev, mem, c, events);
  detectAmp(at, prev, mem, c, events);
  detectWind(at, mem, c, events);
  detectCurrent(at, mem, c, events);
  detectHs(at, mem, c, events);
  detectWxMarina(at, along, mem, c, events);
  detectDepth(at, mem, c, events);
  detectAhead(at, along, mem, c, events);
  for (const ev of events) {
    ev.skipper = skipperSnapshot(ev.type, ctx.orders, ev.payload, ctx.lang);
  }
  return { events, memory: mem };
}
