/**
 * Replay narré de l'expédition (commentaire 5 du porteur) : rejouer la
 * route **de Saint-Maur à la position d'aujourd'hui** sur l'horloge officielle,
 * en racontant. Pur, testé : le temps rejoué avance à `secondsPerDay`, la
 * position vient de l'horloge, le vent des GRIB déjà journalisés, les cartes
 * des lignes du journal (escales, ZEE, AMP, ports d'entrée, météo, notes).
 * Rien n'est inventé : pas de ligne de journal, pas de carte.
 */
import { DEFAULT_T0_ISO, sampleClockAtTime } from "./voyageClock.js";
import { expeditionStory, officialDatedStops } from "./expeditionStory.js";
import { cardFromJournalEntry, JOURNAL_CARD_KINDS } from "./momentCard.js";
import { haversineNm, unwrapLon, wrapLon } from "../utils/geo.js";

export { cardFromJournalEntry };
export const CARD_KINDS = JOURNAL_CARD_KINDS;

export const DEFAULT_SECONDS_PER_DAY = 1;
export const MIN_CARD_MS = 2500;
export const FILM_TARGET_SECONDS = 150;
export const FILM_TARGET_SECONDS_LONG = 180;
export const FILM_RATE_MIN = 0.9;
export const FILM_RATE_MAX = 1.25;
export const FILM_CALIBRATE_SLACK_S = 8;
export const FILM_ZOOM_MIN = 3;
export const FILM_ZOOM_MAX = 7;
export const FILM_FLY_SECONDS = 1.2;
/** Recalcul Leaflet au plus toutes les N frames pendant le film. */
export const FILM_RESET_EVERY = 36;
/** Le bateau reste dans les 40 % centraux de l'écran. */
export const FILM_BOAT_KEEP_FRAC = 0.4;
export const FILM_VIEW_HZ = 30;
export const FILM_MIN_CHAPTER_SECONDS = 12;
export const FILM_RECALE_MS = 300;
export const FILM_BEHIND_SPEED = 0.7;
/** Compensation serveur RG14 (nom du lieu − 12). Le client ne la rajoute plus. */
export const FILM_VOICE_LOOKAHEAD_CHARS = 12;
/** Prédiction entre deux mots : plutôt lent (EN / voix macOS) pour ne pas lâcher le bateau devant. */
export const FILM_VOICE_CPS_DEFAULT = 12;
export const FILM_VOICE_CPS_MIN = 6;
export const FILM_VOICE_CPS_MAX = 40;
export const FILM_PAN_MAX_SCREEN = 0.02;
/** Gouverneur RG12 : vitesse écran bornée, réglable (px / s à la frame). */
export const FILM_V_MIN_PX_S = 24;
export const FILM_V_MAX_PX_S = 180;
/** Après la phrase d'escale, le temps-film rejoint le départ suivant en ≤ 1 s. */
export const FILM_QUAY_SKIP_MS = 1000;
export const FILM_QUAY_NM_EPS = 0.75;
const WIND_WINDOW_MS = 4 * 3600 * 1000;

function lerpNum(a, b, t) {
  const x = Number(a);
  const y = Number(b);
  if (!Number.isFinite(x)) return y;
  if (!Number.isFinite(y)) return x;
  return x + t * (y - x);
}

function ms(iso) {
  const t = typeof iso === "number" ? iso : Date.parse(iso || "");
  return Number.isFinite(t) ? t : null;
}

/** Wall-clock milliseconds of replay per millisecond of expedition. */
export function replayScale(secondsPerDay = DEFAULT_SECONDS_PER_DAY) {
  return (Math.max(0.05, Number(secondsPerDay) || DEFAULT_SECONDS_PER_DAY) * 1000) / 86400000;
}

/** The replay window: from the official departure to now (never beyond). */
export function replayWindow(clock, nowMs) {
  const t0 = ms(clock?.t0);
  const end = Number.isFinite(nowMs) ? nowMs : Date.now();
  if (t0 == null || end <= t0) return null;
  return { startMs: t0, endMs: end, days: (end - t0) / 86400000 };
}

/** Advance the replayed instant by `dtMs` of wall clock; clamps at the end. */
export function advance(tMs, dtMs, window, secondsPerDay = DEFAULT_SECONDS_PER_DAY) {
  if (!window) return { tMs, done: true };
  const next = tMs + dtMs / replayScale(secondsPerDay);
  if (next >= window.endMs) return { tMs: window.endMs, done: true };
  return { tMs: next, done: false };
}

/** Journal entries (any shape the summary serves) sorted by time, once. */
export function journalTimeline(journal) {
  const all = [...(journal?.events || []), ...(journal?.latest || journal?.entries || [])];
  const seen = new Set();
  return all
    .filter((e) => {
      if (!e?.kind || ms(e.t) == null) return false;
      const id = e.id || `${e.kind}:${e.t}`;
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    })
    .sort((a, b) => ms(a.t) - ms(b.t));
}

/** The GRIB reading journaled closest to `tMs` (≤ 4 h away), or null. */
export function windFromJournalAt(timeline, tMs) {
  let best = null;
  let bestD = Infinity;
  for (const e of timeline) {
    if (e.kind !== "grib" || !Number.isFinite(e.windKnots)) continue;
    const d = Math.abs(ms(e.t) - tMs);
    if (d < bestD) { bestD = d; best = e; }
  }
  if (!best || bestD > WIND_WINDOW_MS) return null;
  return { windKnots: best.windKnots, dirFromDeg: best.dirFromDeg ?? null, hs: best.hs ?? null, model: best.model || null, kind: "forecast" };
}

/**
 * The boat at the replayed instant: the clock's sample, dated, with the wind
 * the journal recorded then. Same shape as the live sample the scene reads.
 */
/**
 * Position le long du trait (sommets consécutifs, lon dépliée).
 * Continue aux sommets : limite à gauche = limite à droite.
 */
export function positionAt(clock, tMs) {
  const verts = clock?.vertices || [];
  if (!verts.length) return null;
  const t0 = Date.parse(clock.t0);
  if (!Number.isFinite(t0) || !Number.isFinite(tMs)) return null;
  const tHours = (tMs - t0) / 3600000;
  const pts = [];
  let prevLon = null;
  for (const v of verts) {
    if (!Number.isFinite(v.lat) || !Number.isFinite(v.lon) || !Number.isFinite(v.tHours)) continue;
    const lon = prevLon == null ? v.lon : unwrapLon(prevLon, v.lon);
    pts.push({ lat: v.lat, lon, tHours: v.tHours, sailNm: v.sailNm, filmNm: v.filmNm });
    prevLon = lon;
  }
  if (!pts.length) return null;
  if (tHours <= pts[0].tHours) {
    return { lat: pts[0].lat, lon: pts[0].lon, sailNm: pts[0].sailNm, filmNm: pts[0].filmNm };
  }
  const last = pts[pts.length - 1];
  if (tHours >= last.tHours) {
    return { lat: last.lat, lon: last.lon, sailNm: last.sailNm, filmNm: last.filmNm };
  }
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (tHours > b.tHours) continue;
    const span = b.tHours - a.tHours;
    if (!(span > 1e-12)) {
      return { lat: b.lat, lon: b.lon, sailNm: b.sailNm, filmNm: b.filmNm };
    }
    const u = (tHours - a.tHours) / span;
    return {
      lat: a.lat + u * (b.lat - a.lat),
      lon: a.lon + u * (b.lon - a.lon),
      sailNm: lerpNum(a.sailNm, b.sailNm, u),
      filmNm: lerpNum(a.filmNm, b.filmNm, u),
    };
  }
  return { lat: last.lat, lon: last.lon, sailNm: last.sailNm, filmNm: last.filmNm };
}

/** Expedition-ms per wall-second for a planned chapter (F1 share). */
export function chapterNominalRate(chapter) {
  const seconds = Number(chapter?.seconds);
  const span = Number(chapter?.tB) - Number(chapter?.tA);
  if (!(seconds > 0) || !Number.isFinite(span) || span <= 0) return 0;
  return span / seconds;
}

/**
 * One rAF step of replayed time. Nominal advance ; onboundary target
 * recales in ≤ 300 ms ; never a visible backward jump (0.7× if behind).
 */
export function advanceReplayTime({
  t,
  dt,
  chapter,
  targetT = null,
  recaleRemainMs = 0,
  capT = null,
} = {}) {
  const nominal = chapterNominalRate(chapter);
  const wall = Math.max(0, Number(dt) || 0);
  const tA = Number(chapter?.tA);
  const tB = Number(chapter?.tB);
  let next = Number(t);
  if (!Number.isFinite(next)) next = Number.isFinite(tA) ? tA : 0;
  let remain = Math.max(0, Number(recaleRemainMs) || 0);
  const hasTarget = targetT != null && Number.isFinite(Number(targetT));
  const target = hasTarget ? Number(targetT) : null;

  if (hasTarget && target < next - 1e-9) {
    next += wall * nominal * FILM_BEHIND_SPEED;
    remain = 0;
  } else if (hasTarget && target > next + 1e-9 && remain > 0) {
    const blend = Math.min(1, (wall * 1000) / remain);
    next += (target - next) * blend;
    remain = Math.max(0, remain - wall * 1000);
    if (remain <= 1e-6) {
      next = target;
      remain = 0;
    }
  } else {
    next += wall * nominal;
    remain = Math.max(0, remain - wall * 1000);
  }

  if (Number.isFinite(tA)) next = Math.max(tA, next);
  if (Number.isFinite(tB)) next = Math.min(tB, next);
  // Plafond (27 sept.) : mené par la voix, le bateau n'est jamais plus loin que ce qui est dit.
  if (capT != null && Number.isFinite(Number(capT))) next = Math.min(next, Math.max(Number.isFinite(tA) ? tA : -Infinity, Number(capT)));
  return { t: next, recaleRemainMs: remain };
}

/**
 * Caractère prédit au débit mesuré depuis la dernière frontière de mot.
 * Plafonné à la fin de la phrase en cours : on n'entre pas dans la suivante
 * tant que la voix ne l'a pas commencée (le bateau suit la voix).
 */
export function predictVoiceChar({
  lastBoundaryChar = 0,
  sinceBoundaryS = 0,
  cps = FILM_VOICE_CPS_DEFAULT,
  chars = Infinity,
  sentenceEndChar = Infinity,
} = {}) {
  const rate = Math.max(FILM_VOICE_CPS_MIN, Math.min(FILM_VOICE_CPS_MAX, Number(cps) || FILM_VOICE_CPS_DEFAULT));
  const last = Math.max(0, Number(lastBoundaryChar) || 0);
  const since = Math.max(0, Number(sinceBoundaryS) || 0);
  const pred = last + rate * since;
  const capChars = Number.isFinite(Number(chars)) && Number(chars) > 0 ? Number(chars) : Infinity;
  const capSent = Number.isFinite(Number(sentenceEndChar)) ? Number(sentenceEndChar) : Infinity;
  return Math.max(0, Math.min(pred, capChars, capSent));
}

/**
 * Pas mené par la voix : entre deux frontières, la cible avance au
 * débit mesuré ; une frontière ne fait qu'une correction ≤ 300 ms. Plus de
 * fraction dt/horizon d'un écart figé (dent de scie, rapport 6,8).
 */
export function voiceLedStep({
  t, dt, chapter, plan, chapterIdx, charIdx, cps = FILM_VOICE_CPS_DEFAULT,
  lookahead = 0,
  lastBoundaryChar,
  sinceBoundaryS = 0,
  recaleRemainMs = 0,
} = {}) {
  const rate = Math.max(FILM_VOICE_CPS_MIN, Math.min(FILM_VOICE_CPS_MAX, Number(cps) || FILM_VOICE_CPS_DEFAULT));
  const ahead = Math.max(0, Number(lookahead) || 0);
  const lastB = lastBoundaryChar != null ? Number(lastBoundaryChar) : (Number(charIdx) || 0);
  const sent = sentenceSpan(chapter, lastB);
  const pred = predictVoiceChar({
    lastBoundaryChar: lastB,
    sinceBoundaryS,
    cps: rate,
    chars: chapter?.chars,
    sentenceEndChar: sent?.end,
  });
  const target = plan?.timeAt ? plan.timeAt(chapterIdx, pred + ahead) : null;
  const remain = Math.max(0, Number(recaleRemainMs) || 0);
  if (remain > 0) {
    return advanceReplayTime({
      t, dt, chapter, targetT: target, recaleRemainMs: remain, capT: target,
    });
  }
  let next = Number(t);
  const tA = Number(chapter?.tA);
  const tB = Number(chapter?.tB);
  if (!Number.isFinite(next)) next = Number.isFinite(tA) ? tA : 0;
  if (target != null && Number.isFinite(target)) {
    if (target < next - 1e-9) {
      next += Math.max(0, Number(dt) || 0) * chapterNominalRate(chapter) * FILM_BEHIND_SPEED;
    } else {
      next = target;
    }
  }
  if (Number.isFinite(tA)) next = Math.max(tA, next);
  if (Number.isFinite(tB)) next = Math.min(tB, next);
  if (target != null && Number.isFinite(target)) {
    next = Math.min(next, Math.max(Number.isFinite(tA) ? tA : -Infinity, target));
  }
  return { t: next, recaleRemainMs: 0, predictedChar: pred };
}

/** Débit mesuré de la voix (caractères/s) sur le chapitre en cours, borné ; défaut si trop tôt. */
export function measuredCps(charIdx, elapsedMs, fallback = FILM_VOICE_CPS_DEFAULT) {
  const c = Number(charIdx) || 0;
  const s = (Number(elapsedMs) || 0) / 1000;
  if (c < 20 || s < 1.5) return fallback;
  return Math.max(FILM_VOICE_CPS_MIN, Math.min(FILM_VOICE_CPS_MAX, c / s));
}

/** Pixels par mille nautique (Mercateur web) au zoom et à la latitude du chapitre. */
export function pixelsPerNauticalMile(zoom, lat = 0) {
  const z = Number(zoom);
  const exp = Number.isFinite(z) ? z : 5;
  const phi = (Number(lat) || 0) * (Math.PI / 180);
  const cos = Math.max(0.2, Math.cos(phi));
  return (256 * (2 ** exp)) / (21600 * cos);
}

/** Zoom de chapitre sans carte : largeur de jambe → [3 ; 5]. */
export function chapterZoomEstimate(leg) {
  const aLat = Number(leg?.fromLat);
  const aLon = Number(leg?.fromLon);
  const bLat = Number(leg?.toLat);
  const bLon = Number(leg?.toLon);
  if (![aLat, aLon, bLat, bLon].every(Number.isFinite)) return 5;
  const span = haversineNm(aLat, aLon, bLat, bLon);
  if (span > 2500) return 3;
  if (span > 800) return 4;
  return 5;
}

function clockEndMs(clock) {
  const t0 = Date.parse(clock?.t0 || "");
  const last = (clock?.vertices || []).at(-1);
  if (!Number.isFinite(t0) || !Number.isFinite(last?.tHours)) return null;
  return t0 + last.tHours * 3600000;
}

/** Instant où le bateau a parcouru `dNm` milles géographiques depuis `tMs`. */
export function timeAfterNm(clock, tMs, dNm, tCap = null) {
  const start = positionAt(clock, tMs);
  if (!start || !(Number(dNm) > 0)) return tMs;
  const end = Number.isFinite(Number(tCap)) ? Number(tCap) : clockEndMs(clock);
  if (!Number.isFinite(end) || end <= tMs) return tMs;
  const far = positionAt(clock, end);
  const maxNm = far ? haversineNm(start.lat, start.lon, far.lat, far.lon) : 0;
  if (maxNm <= Number(dNm)) return end;
  let lo = Number(tMs);
  let hi = end;
  for (let k = 0; k < 24; k += 1) {
    const mid = (lo + hi) / 2;
    const p = positionAt(clock, mid);
    const d = p ? haversineNm(start.lat, start.lon, p.lat, p.lon) : 0;
    if (d < Number(dNm)) lo = mid;
    else hi = mid;
  }
  return hi;
}

/** Phrase courante (index de caractères + instants d'ancre). */
export function sentenceSpan(chapter, charIdx) {
  const text = String(chapter?.text || "");
  const chars = Math.max(1, Number(chapter?.chars) || text.length || 1);
  const starts = Array.isArray(chapter?.sentenceStarts) && chapter.sentenceStarts.length
    ? chapter.sentenceStarts.map(Number).filter((n) => Number.isFinite(n) && n >= 0)
    : sentenceStartsFromText(text);
  const x = Math.max(0, Math.min(chars, Number(charIdx) || 0));
  let start = 0;
  let end = chars;
  for (let i = 0; i < starts.length; i += 1) {
    const a = starts[i];
    const b = i + 1 < starts.length ? starts[i + 1] : chars;
    if (x + 1e-9 >= a) {
      start = a;
      end = b;
    }
  }
  return {
    start,
    end,
    startT: anchoredTimeAt(chapter, start),
    endT: anchoredTimeAt(chapter, end),
  };
}

/** L'intervalle [tA, tB] ne déplace pas le bateau à l'écran (quai, route terrestre). */
export function sentenceIsStationary(clock, tA, tB, eps = FILM_QUAY_NM_EPS) {
  const a = positionAt(clock, tA);
  const b = positionAt(clock, tB);
  if (!a || !b) return false;
  return haversineNm(a.lat, a.lon, b.lat, b.lon) <= eps;
}

/** Premier instant, après `fromT`, où une phrase suivante déplace le bateau. */
export function nextMovingTime(clock, chapter, fromT, { eps = FILM_QUAY_NM_EPS } = {}) {
  const text = String(chapter?.text || "");
  const starts = Array.isArray(chapter?.sentenceStarts) && chapter.sentenceStarts.length
    ? chapter.sentenceStarts
    : sentenceStartsFromText(text);
  const tFrom = Number(fromT);
  for (const s of starts) {
    const span = sentenceSpan(chapter, s);
    if (!Number.isFinite(span.startT) || span.startT + 1 < tFrom) continue;
    if (!sentenceIsStationary(clock, span.startT, span.endT, eps)) return span.startT;
  }
  const tB = Number(chapter?.tB);
  if (clock && Number.isFinite(tFrom) && Number.isFinite(tB) && tB > tFrom) {
    const n0 = positionAt(clock, tFrom);
    if (n0) {
      const moved = timeAfterNm(clock, tFrom, eps + 0.05, tB);
      if (moved > tFrom + 1) return moved;
    }
  }
  return Number.isFinite(tB) ? tB : tFrom;
}

/**
 * Borne la vitesse écran [v_min, v_max]. Jamais de recul ; à quai on n'invente
 * pas de route (le saut d'escale est une rampe à part). Le bateau ne dépasse
 * pas la cible (il suit la voix, jamais l'inverse).
 */
export function governReplayTime({
  t,
  desiredT,
  dt,
  clock,
  zoom,
  lat,
  atQuay = false,
  vMin = FILM_V_MIN_PX_S,
  vMax = FILM_V_MAX_PX_S,
  tCap = null,
} = {}) {
  const cur = Number(t);
  const want = Number(desiredT);
  if (!Number.isFinite(cur)) return { t: want, pxPerS: 0 };
  if (!Number.isFinite(want) || want <= cur + 1e-6) return { t: cur, pxPerS: 0 };
  const wall = Math.max(1e-6, Number(dt) || 0);
  if (!clock) return { t: want, pxPerS: 0 };
  const p0 = positionAt(clock, cur);
  const p1 = positionAt(clock, want);
  const dNm = (p0 && p1) ? haversineNm(p0.lat, p0.lon, p1.lat, p1.lon) : 0;
  const pxNm = pixelsPerNauticalMile(zoom, p0?.lat ?? lat);
  const pxPerS = (dNm / wall) * pxNm;
  if (atQuay || dNm <= FILM_QUAY_NM_EPS) return { t: want, pxPerS };
  const cap = Number.isFinite(Number(tCap)) ? Number(tCap) : want;
  if (pxPerS > vMax && pxNm > 0) {
    const next = timeAfterNm(clock, cur, (vMax / pxNm) * wall, cap);
    return { t: Math.min(want, next), pxPerS: vMax };
  }
  if (pxPerS < vMin && pxNm > 0) {
    const next = timeAfterNm(clock, cur, (vMin / pxNm) * wall, cap);
    return { t: Math.min(want, next), pxPerS: Math.min(vMin, (dNm / wall) * pxNm) };
  }
  return { t: want, pxPerS };
}

/** Attente de la voix : seulement après la phrase, jamais une coupure. */
export function voiceShouldWait({
  t,
  sentenceEndT,
  phraseEnded = false,
  atQuay = false,
  slackMs = 80,
} = {}) {
  if (!phraseEnded) return { wait: false, cut: false, skip: false };
  if (atQuay) return { wait: true, cut: false, skip: true };
  const end = Number(sentenceEndT);
  const now = Number(t);
  if (Number.isFinite(end) && Number.isFinite(now) && now + slackMs < end) {
    return { wait: true, cut: false, skip: false };
  }
  return { wait: false, cut: false, skip: false };
}

/** Rampe ≤ 1 s du quai au départ suivant (smoothstep). */
export function skipQuayStep({
  fromT, toT, startedAt, now, durationMs = FILM_QUAY_SKIP_MS,
} = {}) {
  const dur = Math.max(1, Number(durationMs) || FILM_QUAY_SKIP_MS);
  const elapsed = Math.max(0, Number(now) - Number(startedAt));
  const u = Math.max(0, Math.min(1, elapsed / dur));
  const ease = u * u * (3 - 2 * u);
  const a = Number(fromT);
  const b = Number(toT);
  const t = Number.isFinite(a) && Number.isFinite(b) ? a + (b - a) * ease : a;
  return { t, done: u >= 1, u };
}

/**
 * Un pas de temps-film : prédiction voix (ou ancre linéaire), gouverneur,
 * attente en fin de phrase, saut d'escale. Pur, testé.
 */
export function stepFilmTime({
  t,
  dt,
  chapter,
  plan,
  chapterIdx,
  charIdx = 0,
  cps,
  lookahead,
  lastBoundaryChar,
  sinceBoundaryS,
  recaleRemainMs = 0,
  clock,
  zoom,
  lat,
  voiceLed = false,
  phraseEnded = false,
  skipRamp = null,
  nowMs = 0,
} = {}) {
  const sent = sentenceSpan(chapter, charIdx);
  const atQuay = Boolean(clock) && sentenceIsStationary(clock, sent.startT, sent.endT);
  const z = Number.isFinite(Number(zoom)) ? Number(zoom) : chapterZoomEstimate(chapter);
  const phi = Number.isFinite(Number(lat)) ? Number(lat) : Number(chapter?.fromLat) || 0;

  if (skipRamp && skipRamp.toT != null) {
    const sk = skipQuayStep({ ...skipRamp, now: nowMs });
    return {
      t: sk.t,
      recaleRemainMs: 0,
      skipRamp: sk.done ? null : skipRamp,
      voiceHold: !sk.done,
      atQuay: true,
      pxPerS: 0,
    };
  }

  if (phraseEnded && atQuay) {
    const toT = nextMovingTime(clock, chapter, Math.max(Number(t) || sent.endT, sent.endT));
    if (Number.isFinite(toT) && toT > (Number(t) || 0) + 50) {
      const ramp = {
        fromT: Number(t),
        toT,
        startedAt: nowMs,
        durationMs: FILM_QUAY_SKIP_MS,
      };
      const sk = skipQuayStep({ ...ramp, now: nowMs });
      return {
        t: sk.t,
        recaleRemainMs: 0,
        skipRamp: sk.done ? null : ramp,
        voiceHold: true,
        atQuay: true,
        pxPerS: 0,
      };
    }
  }

  let desired = Number(t);
  let recale = Math.max(0, Number(recaleRemainMs) || 0);
  if (voiceLed) {
    const step = voiceLedStep({
      t, dt, chapter, plan, chapterIdx, charIdx, cps, lookahead,
      lastBoundaryChar, sinceBoundaryS, recaleRemainMs: recale,
    });
    desired = step.t;
    recale = step.recaleRemainMs;
  } else if (plan?.timeAt) {
    desired = plan.timeAt(chapterIdx, charIdx);
  }

  if (phraseEnded && !atQuay && Number.isFinite(sent.endT) && desired < sent.endT) {
    desired = sent.endT;
  }

  // RC52 : tant que la phrase n'est pas finie, ne pas rester / viser tB.
  let fromT = Number(t);
  if (!phraseEnded) {
    const phraseT = plan?.timeAt ? plan.timeAt(chapterIdx, charIdx) : sent.startT;
    const tB = Number(chapter?.tB);
    const lastSentence = sent.end + 1e-6 >= (Number(chapter?.chars) || sent.end);
    if (Number.isFinite(sent.endT) && Number.isFinite(desired)) {
      desired = Math.min(desired, sent.endT);
    }
    if (
      Number.isFinite(fromT) && Number.isFinite(tB) && fromT + 2 >= tB && !lastSentence
      && Number.isFinite(phraseT) && phraseT + 1 < tB
    ) {
      fromT = phraseT;
      desired = phraseT;
    } else if (Number.isFinite(sent.endT) && Number.isFinite(fromT) && fromT > sent.endT) {
      fromT = Number.isFinite(phraseT) ? Math.min(phraseT, sent.endT) : sent.endT;
      desired = fromT;
    }
  }

  const gov = governReplayTime({
    t: fromT,
    desiredT: desired,
    dt,
    clock,
    zoom: z,
    lat: phi,
    atQuay: atQuay && !phraseEnded,
    // Voice-led: never let v_min pull the boat past what is being said.
    // RC52 : même mené par la voix, pas au-delà de la phrase en cours.
    tCap: phraseEnded && voiceLed ? desired : sent.endT,
  });
  const wait = voiceShouldWait({
    t: gov.t,
    sentenceEndT: sent.endT,
    phraseEnded,
    atQuay,
  });
  return {
    t: gov.t,
    recaleRemainMs: recale,
    skipRamp: null,
    voiceHold: wait.wait,
    atQuay,
    pxPerS: gov.pxPerS,
  };
}

export function replaySample(clock, tMs, timeline = []) {
  const s = sampleClockAtTime(clock, new Date(tMs));
  if (!s || !Number.isFinite(s.lat)) return null;
  const pos = positionAt(clock, tMs);
  const wind = windFromJournalAt(timeline, tMs);
  return {
    ...s,
    ...(pos && Number.isFinite(pos.lat) ? {
      lat: pos.lat,
      lon: pos.lon,
      sailNm: Number.isFinite(pos.sailNm) ? pos.sailNm : s.sailNm,
      filmNm: Number.isFinite(pos.filmNm) ? pos.filmNm : s.filmNm,
    } : {}),
    iso: new Date(tMs).toISOString(),
    replay: true,
    kind: wind ? "forecast" : "climatology",
    windKnots: wind ? wind.windKnots : (s.windKnots ?? null),
    dirFromDeg: wind ? wind.dirFromDeg : (s.dirFromDeg ?? null),
    hs: wind ? wind.hs : null,
    model: wind ? wind.model : null,
  };
}

/**
 * Écart maximal (milles) entre la position d'une ligne du journal et le bateau
 * du film à la même date. Au-delà, la ligne a été datée sur un autre planning
 * (stock figé, ETA recalculée) : l'entrée en ZEE Nouvelle-Calédonie du 14 oct.
 * s'affichait quand le film passait Papeete. Une carte fausse ne vaut pas mieux
 * que pas de carte.
 */
export const FILM_CARD_MAX_NM = 60;

/** True when the journal line sits where the film boat is at its date (or has no position). */
export function journalEventOnFilm(e, clock, tMs = ms(e?.t), maxNm = FILM_CARD_MAX_NM) {
  if (!clock || !e) return true;
  const lat = Number(e.lat);
  const lon = Number(e.lon);
  if (e.lat == null || e.lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return true;
  const pos = positionAt(clock, tMs);
  if (!pos || !Number.isFinite(pos.lat) || !Number.isFinite(pos.lon)) return true;
  return haversineNm(lat, wrapLon(lon), pos.lat, wrapLon(pos.lon)) <= maxNm;
}

/**
 * Journal lines that fall in (fromMs, toMs], as cards, in order. A ZEE
 * *exit* is not a card: entering the next zone (or nothing, high seas) says
 * it, and a replay has one second per day to spend.
 */
export function cardsBetween(timeline, fromMs, toMs, lang = "fr", clock = null) {
  const out = [];
  for (const e of timeline) {
    const t = ms(e.t);
    if (t == null || t <= fromMs || t > toMs) continue;
    if (e.kind === "zee" && e.event === "exit") continue;
    if (!journalEventOnFilm(e, clock, t)) continue;
    const card = cardFromJournalEntry(e, lang);
    if (card) out.push(card);
  }
  return out;
}

/** Stops, weather and notes matter more than the tenth port of entry: keep the queue short. */
export const QUEUE_MAX = 4;
const LOW_PRIORITY = new Set(["poe", "zee", "amp"]);

export function trimQueue(queue, max = QUEUE_MAX) {
  if (queue.length <= max) return queue;
  const kept = [];
  let toDrop = queue.length - max;
  for (const card of queue) {
    if (toDrop > 0 && LOW_PRIORITY.has(card.kind)) { toDrop -= 1; continue; }
    kept.push(card);
  }
  return kept.slice(-max);
}

/** How long a card may stay: the queue must not fall behind the replay. */
export function cardDwellMs(queueLength, { min = 900, max = MIN_CARD_MS } = {}) {
  if (queueLength <= 0) return max;
  return Math.max(min, Math.round(max / Math.max(1, queueLength)));
}

/** 0 → 1 along the replay. */
export function replayProgress(tMs, window) {
  if (!window || window.endMs <= window.startMs) return 0;
  return Math.max(0, Math.min(1, (tMs - window.startMs) / (window.endMs - window.startMs)));
}

export function clampFilmRate(rate) {
  const n = Number(rate);
  if (!Number.isFinite(n)) return 1;
  return Math.max(FILM_RATE_MIN, Math.min(FILM_RATE_MAX, n));
}

/**
 * After chapter 1, scale `utterance.rate` so the remaining characters land
 * on the leftover budget. Always clamped to [0.9, 1.25].
 */
export function calibrateRate({
  chapterChars,
  elapsedSeconds,
  remainingChars,
  remainingBudgetSeconds,
} = {}) {
  const chars = Number(chapterChars);
  const elapsed = Number(elapsedSeconds);
  if (!(chars > 0) || !(elapsed > 0)) return 1;
  const remaining = Number(remainingChars) || 0;
  const budget = Number(remainingBudgetSeconds);
  if (!(remaining > 0)) return 1;
  if (!(budget > 0)) return FILM_RATE_MAX;
  const estimated = remaining / (chars / elapsed);
  return clampFilmRate(estimated / budget);
}

function markPos(mark, byName, clock, t, live) {
  const raw = mark ? (byName.get(mark.name) || mark) : null;
  if (Number.isFinite(raw?.lat) && Number.isFinite(raw?.lon)) {
    return { lat: raw.lat, lon: raw.lon };
  }
  if (clock) {
    const s = sampleClockAtTime(clock, new Date(t));
    if (s && Number.isFinite(s.lat)) return { lat: s.lat, lon: s.lon };
  }
  if (Number.isFinite(live?.lat) && Number.isFinite(live?.lon)) {
    return { lat: live.lat, lon: live.lon };
  }
  return { lat: null, lon: null };
}

function marksWithIso(marks, clock) {
  const raw = marks?.length ? marks : (clock?.marks || []);
  const clockMarks = clock?.marks || [];
  return (raw || []).map((m) => {
    if (m?.iso) return m;
    const film = Number(m?.filmNm ?? m?.nm);
    const hit = clockMarks.find((c) => (
      Number.isFinite(film) && Math.abs((c.filmNm ?? c.nm) - film) < 0.6 && (!m?.name || c.name === m.name)
    )) || clockMarks.find((c) => m?.name && c.name === m.name);
    return hit ? { ...m, iso: hit.iso, holdHours: hit.holdHours } : m;
  });
}

/**
 * Chapitres = jambes entre escales du récit existant (F3 apportera
 * le script rédigé). Chaque chapitre porte [tA, tB] et le texte de la jambe.
 */
export function filmChaptersFromStory({
  clock, marks, live, journal = null, lang = "fr", nowMs, t0: storyT0,
} = {}) {
  const merged = marksWithIso(marks, clock);
  const dated = officialDatedStops(merged, clock);
  const byName = new Map((merged || []).map((m) => [m.name, m]));
  const t0 = Date.parse(DEFAULT_T0_ISO);
  const tEnd = ms(live?.iso) || nowMs || Date.now();
  if (t0 == null || !(tEnd > t0)) return [];

  const paragraphs = expeditionStory({
    clock, marks: merged, live, journal, now: live?.iso || tEnd, lang, t0: storyT0,
  }).map((p) => String(p || "").trim()).filter(Boolean);

  const stops = dated.length ? dated : [{ name: "Saint-Maur", iso: clock?.t0, filmNm: 0 }];
  const intervals = [];
  for (let i = 0; i < stops.length; i++) {
    const from = stops[i];
    const to = stops[i + 1];
    const tA = ms(from.iso) ?? (i === 0 ? t0 : null);
    if (tA == null || tA >= tEnd) break;
    const rawB = to ? ms(to.iso) : tEnd;
    const tB = Math.min(rawB == null ? tEnd : rawB, tEnd);
    if (tB <= tA) continue;
    const fromPos = markPos(from, byName, clock, tA, live);
    const toPos = markPos(to || live, byName, clock, tB, live);
    intervals.push({
      id: `leg-${i}`,
      fromName: from.name || "",
      toName: (to && tB < tEnd) ? (to.name || "") : "",
      tA,
      tB,
      fromLat: fromPos.lat,
      fromLon: fromPos.lon,
      toLat: toPos.lat,
      toLon: toPos.lon,
    });
    if (!to || (ms(to.iso) != null && ms(to.iso) >= tEnd)) break;
  }
  if (!intervals.length) {
    const a = markPos(null, byName, clock, t0, live);
    const b = markPos(null, byName, clock, tEnd, live);
    intervals.push({
      id: "leg-0",
      fromName: "Saint-Maur",
      toName: "",
      tA: t0,
      tB: tEnd,
      fromLat: a.lat,
      fromLon: a.lon,
      toLat: b.lat,
      toLon: b.lon,
    });
  }

  return intervals.map((leg, i) => {
    let text = "";
    if (i === 0) text = paragraphs[0] || "";
    else if (i < intervals.length - 1) text = paragraphs[i] || paragraphs[0] || "";
    else text = paragraphs.slice(Math.min(i, paragraphs.length - 1)).join(" ") || paragraphs[0] || "";
    return { ...leg, text };
  });
}

export function chapterAtElapsed(plan, elapsedSeconds) {
  const list = plan?.chapters || [];
  if (!list.length) return null;
  const t = Math.max(0, Number(elapsedSeconds) || 0);
  for (const ch of list) {
    if (t < ch.endWall - 1e-9) return ch;
  }
  return list[list.length - 1];
}

/**
 * Répartit `targetSeconds` au prorata des caractères. `timeAt(i, charIdx)`
 * est monotone : le bateau ne recule jamais.
 */
/** Index de début de chaque phrase (serveur `sentenceStarts`, sinon découpage client). */
export function sentenceStartsFromText(text) {
  const raw = String(text || "");
  if (!raw) return [];
  const parts = raw.split(/(?<=[.!?…])\s+/).filter(Boolean);
  const starts = [];
  let from = 0;
  for (const p of parts) {
    const at = raw.indexOf(p, from);
    const start = at >= 0 ? at : from;
    starts.push(start);
    from = start + p.length;
  }
  return starts;
}

export function filmPlan({ chapters, targetSeconds = FILM_TARGET_SECONDS, keepChapters = false } = {}) {
  const target = Number(targetSeconds);
  const seconds = Number.isFinite(target) && target > 0 ? target : FILM_TARGET_SECONDS;
  const list = (chapters || []).filter((c) => c && (ms(c.tA) != null) && (ms(c.tB) != null) && ms(c.tB) > ms(c.tA));
  const weights = list.map((c) => Math.max(1, String(c.text || "").length));
  const totalChars = weights.reduce((s, n) => s + n, 0) || 1;
  let startWall = 0;
  const planned = list.map((c, i) => {
    const chars = weights[i];
    const share = i === list.length - 1
      ? Math.max(0, seconds - startWall)
      : (chars / totalChars) * seconds;
    const tA = ms(c.tA);
    const tB = ms(c.tB);
    const row = {
      ...c,
      idx: i,
      chars,
      seconds: share,
      startWall,
      endWall: startWall + share,
      tA,
      tB,
    };
    startWall += share;
    return row;
  });
  const merged = (keepChapters ? planned : mergeShortChapters(planned, FILM_MIN_CHAPTER_SECONDS))
    .map((c) => {
      const anchors = chapterAnchors(c);
      return {
        ...c,
        anchors,
        anchorSlopes: monotoneSlopes(
          anchors.map((p) => p.charIdx),
          anchors.map((p) => p.t),
        ),
        sentenceStarts: Array.isArray(c.sentenceStarts) && c.sentenceStarts.length
          ? c.sentenceStarts.map(Number).filter((n) => Number.isFinite(n) && n >= 0)
          : sentenceStartsFromText(c.text),
      };
    });

  function timeAt(chapterIdx, charIdx) {
    if (!merged.length) return null;
    const i = Math.max(0, Math.min(merged.length - 1, Number(chapterIdx) || 0));
    return anchoredTimeAt(merged[i], charIdx);
  }

  return { chapters: merged, targetSeconds: seconds, totalChars, timeAt };
}

/**
 * Ancres phrase → instant (serveur : `anchors: [{charIdx, t}]`).
 * Le charIdx est déjà compensé (nom du lieu − FILM_VOICE_LOOKAHEAD_CHARS).
 * Bornées au chapitre, triées, croissantes, encadrées par (0, tA) et (chars, tB).
 */
export function chapterAnchors(ch) {
  const tA = Number(ch?.tA);
  const tB = Number(ch?.tB);
  const chars = Math.max(1, Number(ch?.chars) || String(ch?.text || "").length || 1);
  if (!Number.isFinite(tA) || !Number.isFinite(tB)) return [];
  const source = ch?.anchors || [];
  const stale = source.some((a) => Number(a?.charIdx) > chars);
  const raw = stale
    ? sentenceStartsFromText(ch?.text).map((charIdx, i, starts) => ({
      charIdx,
      t: starts.length <= 1
        ? tA
        : tA + ((tB - tA) * i) / (starts.length - 1),
    }))
    : source
    .map((a) => ({ charIdx: Number(a?.charIdx), t: ms(a?.t) }))
    .filter((a) => Number.isFinite(a.charIdx) && a.t != null && a.charIdx >= 0 && a.charIdx <= chars)
    .sort((a, b) => a.charIdx - b.charIdx);
  const points = [{ charIdx: 0, t: tA }];
  for (const a of raw) {
    const t = Math.max(tA, Math.min(tB, a.t));
    const last = points[points.length - 1];
    const clamped = Math.max(last.t, t);
    if (a.charIdx <= last.charIdx) {
      last.t = clamped;
      continue;
    }
    points.push({ charIdx: a.charIdx, t: clamped });
  }
  const last = points[points.length - 1];
  if (last.charIdx >= chars) last.t = tB;
  else points.push({ charIdx: chars, t: tB });
  return points;
}

/** Pentes Fritsch–Carlson : interpolation cubique monotone (pente continue aux nœuds). */
export function monotoneSlopes(xs, ys) {
  const n = xs.length;
  const m = new Array(n).fill(0);
  if (n < 2) return m;
  const h = [];
  const d = [];
  for (let i = 0; i < n - 1; i += 1) {
    const span = xs[i + 1] - xs[i];
    h.push(span);
    d.push(span > 1e-12 ? (ys[i + 1] - ys[i]) / span : 0);
  }
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i += 1) {
    if (d[i - 1] * d[i] <= 0) {
      m[i] = 0;
      continue;
    }
    const w1 = 2 * h[i] + h[i - 1];
    const w2 = h[i] + 2 * h[i - 1];
    const den = w1 / d[i - 1] + w2 / d[i];
    m[i] = den > 1e-15 ? (w1 + w2) / den : 0;
  }
  return m;
}

function pchipAt(xs, ys, slopes, x) {
  const n = xs.length;
  if (n === 0) return null;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  let i = 0;
  while (i < n - 2 && x > xs[i + 1]) i += 1;
  const h = xs[i + 1] - xs[i];
  if (!(h > 1e-12)) return ys[i + 1];
  const u = (x - xs[i]) / h;
  const u2 = u * u;
  const u3 = u2 * u;
  const h00 = 2 * u3 - 3 * u2 + 1;
  const h10 = u3 - 2 * u2 + u;
  const h01 = -2 * u3 + 3 * u2;
  const h11 = u3 - u2;
  return h00 * ys[i] + h10 * h * slopes[i] + h01 * ys[i + 1] + h11 * h * slopes[i + 1];
}

/**
 * Instant du trajet à `charIdx` : cubique monotone entre ancres (pente continue).
 * Aux nœuds, la valeur reste celle de l'ancre — le bateau est où la phrase le dit.
 */
export function anchoredTimeAt(ch, charIdx) {
  if (!ch) return null;
  const tA = Number(ch.tA);
  const tB = Number(ch.tB);
  const chars = Math.max(1, Number(ch.chars) || 1);
  const x = Math.max(0, Math.min(chars, Number(charIdx) || 0));
  const points = ch.anchors?.length >= 2 ? ch.anchors : [{ charIdx: 0, t: tA }, { charIdx: chars, t: tB }];
  const xs = points.map((p) => Number(p.charIdx));
  const ys = points.map((p) => Number(p.t));
  if (xs.length < 2 || !xs.every(Number.isFinite) || !ys.every(Number.isFinite)) return tB;
  const slopes = ch.anchorSlopes?.length === xs.length ? ch.anchorSlopes : monotoneSlopes(xs, ys);
  const y = pchipAt(xs, ys, slopes, x);
  if (!Number.isFinite(y)) return tB;
  const lo = Math.min(tA, tB);
  const hi = Math.max(tA, tB);
  return Math.max(lo, Math.min(hi, y));
}

export function mergeShortChapters(planned, minSeconds = FILM_MIN_CHAPTER_SECONDS) {
  if (!planned?.length) return [];
  const out = [];
  for (const ch of planned) {
    const prev = out[out.length - 1];
    if (prev && (prev.seconds < minSeconds || ch.seconds < minSeconds)) {
      const offset = (prev.text || "").length + (prev.text && ch.text ? 1 : 0);
      prev.text = [prev.text, ch.text].filter(Boolean).join(" ");
      prev.events = [
        ...(prev.events || []),
        ...((ch.events || []).map((e) => ({ ...e, charIdx: (Number(e.charIdx) || 0) + offset }))),
      ];
      prev.anchors = [
        ...(prev.anchors || []),
        ...((ch.anchors || []).map((a) => ({ ...a, charIdx: (Number(a.charIdx) || 0) + offset }))),
      ];
      prev.tB = ch.tB;
      prev.toName = ch.toName;
      prev.toLat = ch.toLat;
      prev.toLon = ch.toLon;
      prev.chars += ch.chars;
      prev.seconds += ch.seconds;
      prev.endWall = ch.endWall;
    } else {
      out.push({ ...ch });
    }
  }
  return out.map((c, i) => ({ ...c, idx: i }));
}

export function publishFilmStart(targetSeconds) {
  if (typeof window === "undefined") return;
  window.__naviguideFilm = {
    startedAt: performance.now(),
    ended: false,
    targetSeconds,
  };
}

export function publishFilmEnd() {
  if (typeof window === "undefined") return;
  const prev = window.__naviguideFilm || {};
  const endedAt = performance.now();
  const elapsed = Number.isFinite(prev.startedAt) ? (endedAt - prev.startedAt) / 1000 : null;
  window.__naviguideFilm = { ...prev, ended: true, endedAt, elapsed };
  try {
    window.dispatchEvent(new CustomEvent("naviguide-film-end", { detail: window.__naviguideFilm }));
  } catch { /* jsdom */ }
}
