/**
 * Skipper orders — one character, one number per threshold.
 * Pure functions. No HTTP. No chat. No world search. No extra LLM provider.
 *
 * Cruise = today's E1 constants (eventRules.js). Coastal / Ocean = fixed
 * numbers written here once. No formula at runtime, no second default.
 * The boat (name, L, draft, planning speed) is READ from the polar, never typed.
 *
 * S6: Comfort (soft / normal / hard) moves only the notable-wind step and one
 * notch of Hs alert; the horizon knob (24 / 36 / 48 h) drives the Suivre budget.
 * S7: the Expert drawer may force a few engine numbers, each flagged `source:
 * "expert"` so the story cites what the skipper really set. Gale stays locked.
 */

import { expeditionBoatKnots, trueWindAngle } from "./playSpeeds.js";
import { hasPolarRaw, polarBoatSpeed } from "./polarSpeed.js";

export const PROFILES = Object.freeze(["coastal", "cruise", "ocean"]);
export const DEFAULT_PROFILE = "cruise";
export const COMFORT_DEFAULT = "normal";
export const STORAGE_KEY = "ng.sim.skipperOrders.v1";

/** S6 — Comfort: three steps on the "notable wind" and one notch on Hs alert. Gale never. */
export const COMFORTS = Object.freeze(["soft", "normal", "hard"]);
export const COMFORT_TABLE = Object.freeze({
  soft: Object.freeze({
    id: "soft",
    windShiftKt: -2,
    windShiftDeg: -10,
    hsAlertM: -0.5,
    phrase: Object.freeze({ fr: "Je préviens un peu plus tôt.", en: "I warn a little earlier." }),
  }),
  normal: Object.freeze({
    id: "normal",
    windShiftKt: 0,
    windShiftDeg: 0,
    hsAlertM: 0,
    phrase: Object.freeze({ fr: "", en: "" }),
  }),
  hard: Object.freeze({
    id: "hard",
    windShiftKt: 4,
    windShiftDeg: 15,
    hsAlertM: 0.5,
    phrase: Object.freeze({ fr: "Je laisse passer plus.", en: "I let more go by." }),
  }),
});
/** Coastal / Cruise never turn into a WMO squall (+16 kn) through Comfort alone. */
export const COMFORT_WIND_CAP_KT = 16;

/** S6 — horizon knob (Suivre). Each step is honest: the engine budget follows H (§2.6). */
export const HORIZONS_H = Object.freeze([24, 36, 48]);

/**
 * S7 — Expert drawer "Chiffres": the ids a skipper may force outside the profile.
 * Bounds keep the engine sane. Gale (Beaufort) is never here.
 */
export const EXPERT_FIELDS = Object.freeze({
  // Revue du 19 sept. : le coup de vent se règle ; Beaufort 8 / 7 restent les défauts.
  galeKt: Object.freeze({ min: 20, max: 50, step: 1 }),
  galeHoldKt: Object.freeze({ min: 15, max: 45, step: 1 }),
  galePct: Object.freeze({ min: 5, max: 50, step: 1 }),
  windShiftResetKt: Object.freeze({ min: 1, max: 10, step: 1 }),
  windShiftResetDeg: Object.freeze({ min: 5, max: 45, step: 5 }),
  currentIgnoreKn: Object.freeze({ min: 0.1, max: 1, step: 0.1 }),
  currentInvertDeg: Object.freeze({ min: 60, max: 180, step: 10 }),
  rainMmH: Object.freeze({ min: 1, max: 20, step: 0.5 }),
  rain3hMm: Object.freeze({ min: 2, max: 50, step: 1 }),
  marinaRefugeNm: Object.freeze({ min: 5, max: 80, step: 5 }),
  marinaRefugeCooldownMin: Object.freeze({ min: 60, max: 1440, step: 60 }),
  iciRadiusNm: Object.freeze({ min: 5, max: 40, step: 5 }),
  alongAmpNm: Object.freeze({ min: 5, max: 40, step: 5 }),
  ampAheadMinNm: Object.freeze({ min: 1, max: 30, step: 1 }),
});
export const EXPERT_IDS = Object.freeze(Object.keys(EXPERT_FIELDS));
export const DEFAULT_BOAT = Object.freeze({ name: null, loaM: 14, draftM: 1.4 });
export const SMALL_BOAT_LOA_M = 12;
export const SMALL_BOAT_DRAFT_M = 1.1;
export const COASTAL_SUGGEST_RULE = "Côtier conseillé pour < 12 m";
/** Boat overrides typed by the skipper (Paramètres avancés), bounds keep the engine sane. */
export const BOAT_FIELDS = Object.freeze({
  loaM: Object.freeze({ min: 5, max: 60, step: 0.5 }),
  draftM: Object.freeze({ min: 0.3, max: 6, step: 0.1 }),
});

/** Beaufort 8 / 7. Same in the three profiles. Defaults; Expert may move them. */
const LOCKED = Object.freeze({ galeKt: 34, galeHoldKt: 28 });

/** Engine / expert numbers (hide or S7+). Same in the three profiles in v1. */
const SHARED = Object.freeze({
  galePct: 15,
  windShiftResetKt: 4,
  windShiftResetDeg: 20,
  cooldownNm: 15,
  cooldownMin: 30,
  currentIgnoreKn: 0.3,
  currentInvertDeg: 120,
  ampHysteresisNm: 5,
  ampAheadMinNm: 5,
  marinaRefugeCooldownMin: 360,
  depthCooldownNm: 2,
  routeSampleNm: 12,
  groupNmFast: 80,
  iciRadiusNm: 30,
  alongAmpNm: 15,
});

/** The three characters. Each Hs / depth cell IS the number. */
export const PROFILE_TABLE = Object.freeze({
  coastal: Object.freeze({
    id: "coastal",
    phrase: Object.freeze({ fr: "Je parle tôt.", en: "I speak early." }),
    windShiftKt: 6,
    windShiftDeg: 30,
    hsAlertM: 2.5,
    hsShiftM: 0.6,
    currentShiftKn: 0.6,
    depthAlertM: 8,
    depthLabel: "plateau",
    rainMmH: 3,
    rain3hMm: 8,
    marinaRefugeNm: 15,
    suivreLookaheadH: 24,
    groupNm: 8,
    planningKnDefault: 5,
  }),
  cruise: Object.freeze({
    id: "cruise",
    phrase: Object.freeze({ fr: "Ordres Berry — croisière.", en: "Berry orders — cruise." }),
    windShiftKt: 8,
    windShiftDeg: 40,
    hsAlertM: 3.5,
    hsShiftM: 1.0,
    currentShiftKn: 1.0,
    depthAlertM: 15,
    depthLabel: "plateau",
    rainMmH: 4,
    rain3hMm: 10,
    marinaRefugeNm: 25,
    suivreLookaheadH: 36,
    groupNm: 15,
    planningKnDefault: 7,
  }),
  ocean: Object.freeze({
    id: "ocean",
    phrase: Object.freeze({ fr: "Je ne parle que si ça compte.", en: "I only speak when it matters." }),
    windShiftKt: 16,
    windShiftDeg: 60,
    hsAlertM: 5.0,
    hsShiftM: 1.5,
    currentShiftKn: 1.5,
    depthAlertM: 5,
    depthLabel: "talonnage",
    rainMmH: 6,
    rain3hMm: 15,
    marinaRefugeNm: 40,
    suivreLookaheadH: 48,
    groupNm: 25,
    planningKnDefault: 7,
  }),
});

const RAIN_IDS = new Set(["rainMmH", "rain3hMm", "marinaRefugeNm", "marinaRefugeCooldownMin"]);

const PROFILE_LABEL = Object.freeze({
  coastal: Object.freeze({ fr: "côtier", en: "coastal" }),
  cruise: Object.freeze({ fr: "croisière", en: "cruise" }),
  ocean: Object.freeze({ fr: "large", en: "offshore" }),
});

const COMFORT_LABEL = Object.freeze({
  soft: Object.freeze({ fr: "souple", en: "soft" }),
  normal: Object.freeze({ fr: "normal", en: "normal" }),
  hard: Object.freeze({ fr: "dur", en: "hard" }),
});

/** unit / source / rule per id. `source` ∈ beaufort | wmo | metoffice | usage | derive | ui | engine. */
const META = Object.freeze({
  galeKt: { unit: "kn", source: "beaufort", locked: true, rule: "Beaufort 8" },
  galeHoldKt: { unit: "kn", source: "beaufort", locked: true, rule: "Beaufort 7, fin du coup de vent" },
  galePct: { unit: "%", source: "ui", rule: "part de la rose climatologique" },
  windShiftKt: {
    unit: "kn",
    source: (p) => (p === "ocean" ? "wmo" : "usage"),
    rule: (p) => (p === "ocean" ? "grain OMM +16 kn" : `ça change la toile (${PROFILE_LABEL[p].fr})`),
  },
  windShiftDeg: { unit: "°", source: "usage", rule: (p) => `bascule de vent (${PROFILE_LABEL[p].fr})` },
  windShiftResetKt: { unit: "kn", source: "ui", rule: "retour au calme" },
  windShiftResetDeg: { unit: "°", source: "ui", rule: "retour au calme" },
  cooldownNm: { unit: "nm", source: "engine", rule: "anti-spam" },
  cooldownMin: { unit: "min", source: "engine", rule: "anti-spam" },
  currentShiftKn: { unit: "kn", source: "usage", rule: (p) => `usage routage (${PROFILE_LABEL[p].fr})` },
  currentIgnoreKn: { unit: "kn", source: "usage", rule: "bruit de courant" },
  currentInvertDeg: { unit: "°", source: "usage", rule: "inversion de courant" },
  hsShiftM: { unit: "m", source: "usage", rule: (p) => `variation de houle (${PROFILE_LABEL[p].fr})` },
  hsAlertM: {
    unit: "m",
    source: "usage",
    rule: (p) => ({
      coastal: "constante Côtier 2,5 m — je parle tôt",
      cruise: "constante Croisière E1 3,5 m",
      ocean: "constante Large 5,0 m — je ne parle que si ça compte",
    })[p],
  },
  ampHysteresisNm: { unit: "nm", source: "engine", rule: "hystérésis AMP" },
  ampAheadMinNm: { unit: "nm", source: "ui", rule: "distance minimale devant" },
  rainMmH: { unit: "mm/h", source: "metoffice", rule: "pluie forte Met Office" },
  rain3hMm: { unit: "mm/3h", source: "wmo", rule: "pluie forte OMM sur 3 h" },
  marinaRefugeNm: { unit: "nm", source: "ui", rule: (p) => `repli Plan B (${PROFILE_LABEL[p].fr})` },
  marinaRefugeCooldownMin: { unit: "min", source: "ui", rule: "anti-spam repli" },
  depthAlertM: {
    unit: "m",
    source: "ui",
    rule: (p) => ({
      coastal: "constante Côtier 8 m — plateau",
      cruise: "constante Croisière E1 15 m — plateau",
      ocean: "constante Large 5 m — talonnage",
    })[p],
  },
  depthCooldownNm: { unit: "nm", source: "engine", rule: "anti-spam fond" },
  routeSampleNm: { unit: "nm", source: "engine", rule: "pas des perles" },
  groupNm: { unit: "nm", source: "ui", rule: (p) => `groupement (${PROFILE_LABEL[p].fr})` },
  groupNmFast: { unit: "nm", source: "ui", rule: "groupement film rapide" },
  iciRadiusNm: { unit: "nm", source: "ui", rule: "rayon du sac (Met Éireann côtier)" },
  alongAmpNm: { unit: "nm", source: "ui", rule: "AMP sur le trait" },
  suivreLookaheadH: { unit: "h", source: "usage", rule: (p) => `fenêtre GRIB (${PROFILE_LABEL[p].fr})` },
  suivreLookaheadMaxNm: { unit: "nm", source: "derive", rule: "heures × nœuds" },
  maxPearlsSuivre: { unit: "perles", source: "derive", rule: "ceil(nm / 12)" },
  planningKn: { unit: "kn", source: "usage", rule: null },
});

function isFinitePositive(n) {
  return Number.isFinite(n) && n > 0;
}

/** null / undefined / "" stay unknown (NaN) — Number(null) would lie with 0. */
function measure(v) {
  if (v == null || v === "") return NaN;
  return Number(v);
}

function isEn(lang) {
  return typeof lang === "string" && lang.toLowerCase().startsWith("en");
}

function fmt(n, lang, digits = null) {
  if (!Number.isFinite(n)) return "—";
  const s = digits == null ? String(n) : n.toFixed(digits);
  return isEn(lang) ? s : s.replace(".", ",");
}

export function profileLabel(profile, lang = "fr") {
  const row = PROFILE_LABEL[profile] || PROFILE_LABEL[DEFAULT_PROFILE];
  return isEn(lang) ? row.en : row.fr;
}

export function comfortLabel(comfort, lang = "fr") {
  const row = COMFORT_LABEL[comfort] || COMFORT_LABEL[COMFORT_DEFAULT];
  return isEn(lang) ? row.en : row.fr;
}

/** Budget rule §2.6 — the horizon never lies: nm = H × kn, pearls follow. */
function budgetFrom(hours, planningKn, sampleNm) {
  const h = isFinitePositive(hours) ? hours : PROFILE_TABLE.cruise.suivreLookaheadH;
  const kn = isFinitePositive(planningKn) ? planningKn : PROFILE_TABLE.cruise.planningKnDefault;
  const step = isFinitePositive(sampleNm) ? sampleNm : SHARED.routeSampleNm;
  const maxNm = Math.round(h * kn * 10) / 10;
  return {
    hours: h,
    planningKn: kn,
    sampleNm: step,
    maxNm,
    maxPearls: Math.max(1, Math.ceil(maxNm / step)),
  };
}

/** One boat override, clamped to its bounds. null when unknown id / not a number. */
export function clampBoat(id, value) {
  const f = BOAT_FIELDS[id];
  const n = measure(value);
  // A length or a draft that is not a positive number is no measure at all.
  if (!f || !Number.isFinite(n) || n <= 0) return null;
  const clamped = Math.min(f.max, Math.max(f.min, n));
  return Math.round(clamped * 100) / 100;
}

/** Keep only known boat ids with a finite number inside the bounds. {} when nothing. */
export function sanitizeBoat(boat) {
  const out = {};
  if (!boat || typeof boat !== "object") return out;
  for (const id of Object.keys(BOAT_FIELDS)) {
    const v = clampBoat(id, boat[id]);
    if (v != null) out[id] = v;
  }
  return out;
}

/** Planning speed floor: a polar at 2 kn of wind says 0 — the skipper still plans. */
export const PLANNING_MIN_KN = 3;

/** Croisière : part de la polaire. Défaut 0,85 ; VITE_POLAR_EFFICIENCY. */
const _polarEffRaw = Number(
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_POLAR_EFFICIENCY) || 0.85,
);
export const POLAR_EFFICIENCY = Number.isFinite(_polarEffRaw) && _polarEffRaw > 0
  ? Math.min(1, _polarEffRaw)
  : 0.85;

/**
 * Planning speed = the polar read at the wind of the moment (revue du 19 sept.) :
 * GRIB at the boat in Suivre, climatology of the leg in Simulation. `wind` =
 * { tws, twd, heading, kind: "grib" | "climatology" }. Without a polar table
 * or without wind → the downwind average of the polar (as before) → null.
 * Returns { kn, source, twa, tws } — the numbers the panel and the story cite.
 */
export function planningSpeedFor(polar, wind = null) {
  const tws = Number(wind?.tws);
  const twa = trueWindAngle(Number(wind?.heading), Number(wind?.twd));
  if (Number.isFinite(tws) && twa != null && hasPolarRaw(polar?.raw)) {
    const bs = polarBoatSpeed(polar.raw, twa, tws);
    if (Number.isFinite(bs)) {
      return {
        kn: Math.round(Math.max(PLANNING_MIN_KN, bs * POLAR_EFFICIENCY) * 10) / 10,
        source: wind?.kind === "climatology" ? "climatology" : "grib",
        twa: Math.round(twa),
        tws: Math.round(tws * 10) / 10,
      };
    }
  }
  const hasPolarSpeed = Boolean(polar?.vmg_summary && typeof polar.vmg_summary === "object");
  const kn = hasPolarSpeed ? expeditionBoatKnots(polar) : null;
  if (isFinitePositive(kn)) return { kn: Math.round(kn * 10) / 10, source: "polar", twa: null, tws: null };
  return null;
}

/**
 * Read the boat from the polar. Berry defaults when the polar does not say;
 * what the skipper typed (Paramètres avancés) wins over both. `wind` makes
 * the planning speed follow the polar at the wind of the moment.
 */
export function readBoat(polar, override = null, wind = null) {
  const own = sanitizeBoat(override);
  const loaRaw = Number(polar?.loa_m ?? polar?.loaM);
  const draftRaw = Number(polar?.draft_m ?? polar?.draftM);
  const planning = planningSpeedFor(polar, wind);
  return {
    name: polar?.boat_name ?? polar?.name ?? DEFAULT_BOAT.name,
    expeditionId: polar?.expedition_id ?? null,
    loaM: own.loaM ?? (isFinitePositive(loaRaw) ? loaRaw : DEFAULT_BOAT.loaM),
    draftM: own.draftM ?? (isFinitePositive(draftRaw) ? draftRaw : DEFAULT_BOAT.draftM),
    planningKn: planning?.kn ?? null,
    planningWind: planning && planning.twa != null ? { twa: planning.twa, tws: planning.tws } : null,
    source: {
      name: polar?.boat_name || polar?.name ? "polar" : null,
      loa: own.loaM != null ? "skipper" : (isFinitePositive(loaRaw) ? "polar" : "default"),
      draft: own.draftM != null ? "skipper" : (isFinitePositive(draftRaw) ? "polar" : "default"),
      planningKn: planning?.source ?? "profile",
    },
  };
}

/**
 * A small polar PROPOSES Coastal. Never a silent switch.
 * Only when L / draft were really read from the polar.
 */
export function suggestProfileForBoat(boat) {
  if (!boat) return null;
  const smallLoa = boat.source?.loa === "polar" && boat.loaM < SMALL_BOAT_LOA_M;
  const smallDraft = boat.source?.draft === "polar" && boat.draftM < SMALL_BOAT_DRAFT_M;
  if (!smallLoa && !smallDraft) return null;
  return { profile: "coastal", reason: smallLoa ? "small_loa" : "small_draft" };
}

function metaFor(id, profile) {
  const m = META[id] || {};
  const source = typeof m.source === "function" ? m.source(profile) : (m.source || "ui");
  const rule = typeof m.rule === "function" ? m.rule(profile) : (m.rule ?? null);
  return { unit: m.unit || "", source, rule, locked: Boolean(m.locked) };
}

function round1(n) {
  return Math.round(n * 10) / 10;
}

/** One Expert value, clamped to its bounds. null when unknown id / not a number. */
export function clampExpert(id, value) {
  const f = EXPERT_FIELDS[id];
  const n = measure(value);
  if (!f || !Number.isFinite(n)) return null;
  const clamped = Math.min(f.max, Math.max(f.min, n));
  return Math.round(clamped * 100) / 100;
}

/** Keep only known ids with a finite number inside the bounds. {} when nothing. */
export function sanitizeExpert(expert) {
  const out = {};
  if (!expert || typeof expert !== "object") return out;
  for (const id of EXPERT_IDS) {
    const v = clampExpert(id, expert[id]);
    if (v != null) out[id] = v;
  }
  return out;
}

/**
 * resolveOrders(saved, { polar, mode }) →
 *   { profile, mode, phrase, comfort, comfortPhrase, boat, knobs, expert,
 *     values, thresholds, rainEnabled, rainReason, budget, suggest }
 * One `value` per id. Never two candidates: profile → Comfort delta → Expert
 * override, in that order, and the threshold says which one spoke (`source`).
 */
export function resolveOrders(saved, { polar = null, mode = "simulation", wind = null } = {}) {
  const profile = PROFILES.includes(saved?.profile) ? saved.profile : DEFAULT_PROFILE;
  const comfort = COMFORTS.includes(saved?.comfort) ? saved.comfort : COMFORT_DEFAULT;
  const row = PROFILE_TABLE[profile];
  const cmf = COMFORT_TABLE[comfort];
  const horizonH = HORIZONS_H.includes(saved?.horizonH) ? saved.horizonH : row.suivreLookaheadH;
  const expert = sanitizeExpert(saved?.expert);
  // The end of a gale (hold) always sits under the gale itself.
  if (expert.galeHoldKt != null && expert.galeHoldKt >= (expert.galeKt ?? LOCKED.galeKt)) {
    expert.galeHoldKt = Math.max(EXPERT_FIELDS.galeHoldKt.min, (expert.galeKt ?? LOCKED.galeKt) - 4);
  }
  const boat = readBoat(polar, saved?.boat, wind);
  const planningKn = boat.planningKn ?? row.planningKnDefault;
  const budget = budgetFrom(horizonH, planningKn, SHARED.routeSampleNm);
  const rainEnabled = mode === "suivre";
  const rainReason = rainEnabled ? null : "simulation_no_rain";

  // S6 — Comfort moves the "notable wind" and one notch of Hs alert. Never the gale.
  let windShiftKt = row.windShiftKt + cmf.windShiftKt;
  if (profile !== "ocean") windShiftKt = Math.min(windShiftKt, COMFORT_WIND_CAP_KT);
  windShiftKt = Math.max(windShiftKt, SHARED.windShiftResetKt);
  const windShiftDeg = Math.max(row.windShiftDeg + cmf.windShiftDeg, SHARED.windShiftResetDeg);
  const hsAlertM = round1(Math.max(row.hsAlertM + cmf.hsAlertM, row.hsShiftM));

  const values = Object.freeze({
    ...LOCKED,
    ...SHARED,
    windShiftKt,
    windShiftDeg,
    hsAlertM,
    hsShiftM: row.hsShiftM,
    currentShiftKn: row.currentShiftKn,
    depthAlertM: row.depthAlertM,
    depthLabel: row.depthLabel,
    rainMmH: row.rainMmH,
    rain3hMm: row.rain3hMm,
    marinaRefugeNm: row.marinaRefugeNm,
    suivreLookaheadH: horizonH,
    suivreLookaheadMaxNm: budget.maxNm,
    maxPearlsSuivre: budget.maxPearls,
    planningKn,
    groupNm: row.groupNm,
    // S7 — Expert overrides win, and are flagged as such below.
    ...expert,
  });

  const comfortTouched = new Set(
    comfort === COMFORT_DEFAULT ? [] : ["windShiftKt", "windShiftDeg", "hsAlertM"],
  );
  const thresholds = Object.keys(values)
    .filter((id) => id !== "depthLabel")
    .map((id) => {
      const m = metaFor(id, profile);
      const rain = RAIN_IDS.has(id);
      let source = id === "planningKn" && boat.planningKn != null ? "usage" : m.source;
      let rule = m.rule;
      if (id === "planningKn") {
        if (boat.planningKn == null) rule = `défaut ${PROFILE_LABEL[profile].fr} sans polaire`;
        else if (boat.source.planningKn === "grib") rule = `polaire × vent GRIB (${boat.planningWind.tws} kn, TWA ${boat.planningWind.twa}°)`;
        else if (boat.source.planningKn === "climatology") rule = `polaire × vent typique (${boat.planningWind.tws} kn, TWA ${boat.planningWind.twa}°)`;
        else rule = "polaire (VMG portant)";
      }
      if (id in expert) {
        source = "expert";
        rule = `réglage Expert (profil ${PROFILE_LABEL[profile].fr})`;
      } else if (comfortTouched.has(id)) {
        rule = `${rule} · confort ${COMFORT_LABEL[comfort].fr}`;
      } else if (id === "suivreLookaheadH" && horizonH !== row.suivreLookaheadH) {
        source = "ui";
        rule = "horizon choisi par le skipper";
      }
      return {
        id,
        value: values[id],
        unit: m.unit,
        source,
        rule,
        // Beaufort stays the default; a gale typed by the skipper is not locked.
        locked: m.locked && !(id in expert),
        enabled: rain ? rainEnabled : true,
        reason: rain && !rainEnabled ? rainReason : null,
      };
    });

  const suggest = profile === "coastal" ? null : suggestProfileForBoat(boat);

  return {
    profile,
    mode,
    phrase: row.phrase,
    comfort,
    comfortPhrase: cmf.phrase,
    boat,
    knobs: { horizonH, comfort, horizonDefaultH: row.suivreLookaheadH },
    expert,
    values,
    thresholds,
    rainEnabled,
    rainReason,
    budget,
    suggest,
  };
}

/** Flat values with Cruise defaults when no orders were passed. */
export function thresholdValues(orders) {
  const v = orders?.values;
  if (v && Number.isFinite(v.galeKt) && Number.isFinite(v.hsAlertM) && Number.isFinite(v.depthAlertM)) {
    return v;
  }
  return DEFAULT_ORDERS.values;
}

/** Budget §2.6 from resolved orders (Cruise if none). */
export function lookaheadBudget(orders) {
  if (orders?.budget && isFinitePositive(orders.budget.maxNm)) return orders.budget;
  return DEFAULT_ORDERS.budget;
}

function idsForEvent(type, orders, payload) {
  const p = payload || {};
  const simulation = orders.mode !== "suivre";
  switch (type) {
    case "wind-gale":
      return ["galeKt", "galeHoldKt", ...(simulation && p.galePct != null ? ["galePct"] : [])];
    case "wind-shift":
      return ["windShiftKt", "windShiftDeg"];
    case "current-shift":
      return ["currentShiftKn", ...(p.invert ? ["currentInvertDeg"] : [])];
    case "hs-shift":
      return p.alert === false ? ["hsShiftM"] : ["hsShiftM", "hsAlertM"];
    case "wx-alert": {
      const ids = [];
      const noDetail = p.gale == null && p.hs == null && p.rain == null;
      if (noDetail || p.gale) ids.push("galeKt");
      if (noDetail || p.hs != null) ids.push("hsAlertM");
      if (!simulation && (noDetail || p.rain)) ids.push("rainMmH", "rain3hMm");
      return ids;
    }
    case "marina-refuge":
      return simulation ? [] : ["rainMmH", "rain3hMm", "marinaRefugeNm"];
    case "depth-alert":
      return ["depthAlertM"];
    case "amp-ahead":
      return ["ampAheadMinNm", "alongAmpNm"];
    case "amp-enter":
      return ["iciRadiusNm"];
    default:
      return [];
  }
}

/**
 * thresholdsForEvent(type, orders, payload?) → `used`
 * Only the ids that made THIS event switch. One `value` per id.
 */
export function thresholdsForEvent(type, orders, payload = null) {
  const o = orders?.thresholds ? orders : DEFAULT_ORDERS;
  const byId = new Map(o.thresholds.map((t) => [t.id, t]));
  const seen = new Set();
  const used = [];
  for (const id of idsForEvent(type, o, payload)) {
    if (seen.has(id) || !byId.has(id)) continue;
    seen.add(id);
    const t = byId.get(id);
    used.push({ id, value: t.value, unit: t.unit, source: t.source, rule: t.rule });
  }
  return used;
}

/** Frozen snapshot attached to an event at detection time (§6.2). */
export function skipperSnapshot(type, orders, payload = null, lang = "fr") {
  const o = orders?.thresholds ? orders : DEFAULT_ORDERS;
  return {
    profile: o.profile,
    profile_phrase: isEn(lang) ? o.phrase.en : o.phrase.fr,
    comfort: o.comfort,
    boat: { name: o.boat.name, loaM: o.boat.loaM, draftM: o.boat.draftM },
    used: thresholdsForEvent(type, o, payload),
  };
}

/**
 * Living example from the current bag. Under two lines. FR / EN.
 * "Vent ici 18 kn — je me tais. À 34 kn je parle. Mer 1,4 m — sous 3,5 m."
 */
export function exampleLine(orders, sample = {}, lang = "fr") {
  const T = thresholdValues(orders);
  const en = isEn(lang);
  const parts = [];
  const tws = measure(sample?.tws);
  const hs = measure(sample?.hs);
  const depth = measure(sample?.depthM);
  if (Number.isFinite(tws)) {
    if (tws >= T.galeKt) {
      parts.push(en
        ? `Wind here ${fmt(tws, lang)} kn — gale, I speak.`
        : `Vent ici ${fmt(tws, lang)} kn — coup de vent, je parle.`);
    } else {
      parts.push(en
        ? `Wind here ${fmt(tws, lang)} kn — I stay quiet. At ${T.galeKt} kn I speak.`
        : `Vent ici ${fmt(tws, lang)} kn — je me tais. À ${T.galeKt} kn je parle.`);
    }
  }
  if (Number.isFinite(hs)) {
    if (hs >= T.hsAlertM) {
      parts.push(en
        ? `Sea ${fmt(hs, lang, 1)} m — above ${fmt(T.hsAlertM, lang, 1)} m, I speak.`
        : `Mer ${fmt(hs, lang, 1)} m — au-dessus de ${fmt(T.hsAlertM, lang, 1)} m, je parle.`);
    } else {
      parts.push(en
        ? `Sea ${fmt(hs, lang, 1)} m — under ${fmt(T.hsAlertM, lang, 1)} m.`
        : `Mer ${fmt(hs, lang, 1)} m — sous ${fmt(T.hsAlertM, lang, 1)} m.`);
    }
  }
  if (Number.isFinite(depth) && depth < T.depthAlertM) {
    const label = T.depthLabel === "talonnage"
      ? (en ? "grounding risk" : "risque de talonner")
      : (en ? "shelf ahead" : "on approche du plateau");
    parts.push(en
      ? `Depth ${fmt(depth, lang)} m — under ${T.depthAlertM} m, ${label}.`
      : `Fond ${fmt(depth, lang)} m — sous ${T.depthAlertM} m, ${label}.`);
  }
  if (!parts.length) {
    return en
      ? `No bag here yet. I speak at ${T.galeKt} kn, sea ${fmt(T.hsAlertM, lang, 1)} m, depth ${T.depthAlertM} m.`
      : `Pas encore de sac ici. Je parle à ${T.galeKt} kn, mer ${fmt(T.hsAlertM, lang, 1)} m, fond ${T.depthAlertM} m.`;
  }
  return parts.join(" ");
}

/** Cyan briefing line shown once after a change: "Ordres : croisière · Hs 3,5 m · fond 15 m". */
export function ordersLine(orders, lang = "fr") {
  const o = orders?.values ? orders : DEFAULT_ORDERS;
  const T = o.values;
  const en = isEn(lang);
  const label = profileLabel(o.profile, lang);
  const comfort = o.comfort && o.comfort !== COMFORT_DEFAULT ? ` · ${comfortLabel(o.comfort, lang)}` : "";
  const expertN = o.expert ? Object.keys(o.expert).length : 0;
  const expert = expertN ? (en ? ` · ${expertN} expert` : ` · ${expertN} expert`) : "";
  return en
    ? `Orders: ${label}${comfort} · Hs ${fmt(T.hsAlertM, lang, 1)} m · depth ${T.depthAlertM} m${expert}`
    : `Ordres : ${label}${comfort} · Hs ${fmt(T.hsAlertM, lang, 1)} m · fond ${T.depthAlertM} m${expert}`;
}

/** Depth phrase per profile: shelf (Coastal / Cruise) or grounding (Ocean). */
export function depthPhrase(depthM, orders, lang = "fr") {
  const T = thresholdValues(orders);
  const en = isEn(lang);
  const d = fmt(depthM, lang);
  if (T.depthLabel === "talonnage") {
    return en
      ? `Grounding risk: ${d} m sounded, under ${T.depthAlertM} m.`
      : `Risque de talonner : ${d} m sondés, sous ${T.depthAlertM} m.`;
  }
  return en
    ? `Approaching the shelf: ${d} m sounded, under ${T.depthAlertM} m.`
    : `On approche du plateau : ${d} m sondés, sous ${T.depthAlertM} m.`;
}

/* ---- Persistence (tab + localStorage). Same key since v1; S6/S7 grow the object. ---- */

/**
 * Keep only what the plan allows in `ng.sim.skipperOrders.v1`:
 * `profile` (v1), `comfort`, `horizonH`, `expert` (S6 / S7). Nothing else.
 * Omits defaults so a v1 reader still sees `{ profile }` when nothing changed.
 */
export function sanitizeSaved(obj) {
  const profile = PROFILES.includes(obj?.profile) ? obj.profile : DEFAULT_PROFILE;
  const out = { profile };
  if (COMFORTS.includes(obj?.comfort) && obj.comfort !== COMFORT_DEFAULT) out.comfort = obj.comfort;
  if (HORIZONS_H.includes(obj?.horizonH)) out.horizonH = obj.horizonH;
  const expert = sanitizeExpert(obj?.expert);
  if (Object.keys(expert).length) out.expert = expert;
  const boat = sanitizeBoat(obj?.boat);
  if (Object.keys(boat).length) out.boat = boat;
  return out;
}

export function readSavedOrders(storage) {
  try {
    const raw = storage?.getItem?.(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    return PROFILES.includes(obj?.profile) ? sanitizeSaved(obj) : null;
  } catch {
    return null;
  }
}

export function writeSavedOrders(storage, saved) {
  try {
    storage?.setItem?.(STORAGE_KEY, JSON.stringify(sanitizeSaved(saved)));
    return true;
  } catch {
    return false;
  }
}

export function clearSavedOrders(storage) {
  try {
    storage?.removeItem?.(STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

/** Cruise = today's E1 constants. Simulation mode, no polar. */
export const DEFAULT_ORDERS = Object.freeze(resolveOrders(null, {}));
