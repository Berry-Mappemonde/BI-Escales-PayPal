/** Expedition cruise speed (knots): downwind BS, else 7 kt. */
export const FALLBACK_EXPEDITION_KNOTS = 7;

export function expeditionBoatKnots(polarData) {
  const vmg = polarData?.vmg_summary;
  if (!vmg || typeof vmg !== "object") return FALLBACK_EXPEDITION_KNOTS;
  const samples = [];
  for (const key of ["12", "16", "10", "8"]) {
    const dw = vmg[key]?.downwind;
    const bs = Number(dw?.speed ?? dw?.vmg);
    if (Number.isFinite(bs) && bs > 0) samples.push(bs);
  }
  if (!samples.length) return FALLBACK_EXPEDITION_KNOTS;
  return samples.reduce((a, b) => a + b, 0) / samples.length;
}

/**
 * True-wind angle (0–180): boat heading vs direction the wind comes from.
 */
export function trueWindAngle(headingDeg, windFromDeg) {
  if (!Number.isFinite(headingDeg) || !Number.isFinite(windFromDeg)) return null;
  let d = Math.abs(headingDeg - windFromDeg) % 360;
  if (d > 180) d = 360 - d;
  return d;
}

export const PLAY_PROFILES = ["real", "read", "normal", "fast"];

/**
 * nm/s selon le profil.
 * Fast: Atlantic (La Rochelle → Fort-de-France) in 20 s.
 * Real: boat knots (1 s on screen = 1 s at sea).
 */
export function nmPerSecond(profile, { boatKnots, atlanticNm }) {
  const knots = Number(boatKnots) > 0 ? Number(boatKnots) : FALLBACK_EXPEDITION_KNOTS;
  if (profile === "real") return knots / 3600;
  const atl = Number(atlanticNm) > 100 ? Number(atlanticNm) : 3500;
  if (profile === "fast") return atl / 20;
  if (profile === "read") return atl / 240;
  return atl / 70;
}

/** Durées courtes du film (2:30 / 3:00). L'intégral est la clé 0. */
export const FILM_SHORT_SECONDS = [150, 180];
const FILM_PILL_CPS = 15;

export function filmEstimateRow(seconds, estimates) {
  if (!estimates || typeof estimates !== "object") return null;
  const key = String(Number(seconds) || 0);
  const direct = estimates[key];
  if (direct && typeof direct === "object" && (direct.estimatedSeconds != null || direct.chars != null)) {
    return direct;
  }
  const nested = estimates.fr?.[key] || estimates.en?.[key];
  return nested && typeof nested === "object" ? nested : null;
}

/** Gris seulement si les estimées sont connues et que la variante manque ou dépasse +10 %. */
export function filmVariantAbsent(seconds, estimates) {
  const sec = Number(seconds) || 0;
  if (!(sec > 0)) return false;
  if (estimates == null) return false;
  const row = filmEstimateRow(sec, estimates);
  if (!row) return true;
  const est = Number(row.estimatedSeconds);
  const chars = Number(row.chars);
  const hasEst = Number.isFinite(est) && est > 0;
  const hasChars = Number.isFinite(chars) && chars > 0;
  if (!hasEst && !hasChars) return true;
  const limit = sec * 1.1;
  if (hasChars && chars / FILM_PILL_CPS > limit) return true;
  if (hasEst && est > limit) return true;
  return false;
}

export function filmDurationPill({ seconds, active, estimates } = {}) {
  const absent = filmVariantAbsent(seconds, estimates);
  return {
    absent,
    grey: absent,
    disabled: Boolean(active),
    titleKey: absent ? "fm1VariantAbsent" : "filmDuration",
  };
}

export function filmDurationClass(selected, grey) {
  if (grey) return "opacity-30 cursor-not-allowed";
  if (selected) return "bg-sky-700/70 text-sky-50 border border-sky-300/40";
  return "text-white/70 hover:text-white border border-transparent";
}

/** Estimée affichée : variante absente → intégrale (souvent ≈ 5:35). */
export function filmShownEstimateSeconds(targetSeconds, estimates, fallbackSeconds = 0) {
  const selected = Number(targetSeconds) || 0;
  if (selected > 0 && filmVariantAbsent(selected, estimates)) {
    return filmShownEstimateSeconds(0, estimates, fallbackSeconds);
  }
  const row = filmEstimateRow(selected, estimates);
  const fromMap = Number(row?.estimatedSeconds);
  if (Number.isFinite(fromMap) && fromMap > 0) return fromMap;
  const chars = Number(row?.chars);
  if (Number.isFinite(chars) && chars > 0) return Math.max(1, Math.round(chars / FILM_PILL_CPS));
  const fb = Number(fallbackSeconds);
  return Number.isFinite(fb) && fb > 0 ? fb : 0;
}

export function formatFilmClock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (!s) return "";
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function filmSpeedProfileState({ durationSeconds = 0, estimates = null } = {}) {
  const sec = Number(durationSeconds) || 0;
  const pill = sec > 0
    ? filmDurationPill({ seconds: sec, active: false, estimates })
    : { grey: false, titleKey: "filmSpeedProfile" };
  const estimateSeconds = filmShownEstimateSeconds(sec, estimates, 0);
  return {
    grey: Boolean(pill.grey),
    titleKey: pill.grey ? "fm1VariantAbsent" : (sec > 0 ? "filmDuration" : "filmSpeedProfile"),
    estimateSeconds,
    estimateClock: formatFilmClock(estimateSeconds),
  };
}

/** Screen duration of an air hop, so the plane stays visible on every profile. */
export function airHopSeconds(profile) {
  if (profile === "real") return 8;
  if (profile === "read") return 4.5;
  if (profile === "fast") return 3.2;
  return 3.6;
}
