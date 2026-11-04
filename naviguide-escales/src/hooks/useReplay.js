import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_SECONDS_PER_DAY, MIN_CARD_MS, FILM_RECALE_MS, cardDwellMs, measuredCps, cardsBetween, chapterAtElapsed, chapterZoomEstimate, filmChaptersFromStory, filmPlan, journalTimeline, nextMovingTime, positionAt, publishFilmEnd, publishFilmStart, replayProgress, replaySample, replayWindow, sentenceIsStationary, sentenceSpan, stepFilmTime, trimQueue, voiceShouldWait,
} from "../engine/replay.js";
import { FILM_UI_MS } from "../map/filmCamera.js";
import { buildFilmScript } from "../engine/expeditionStory.js";
import {
  DEFAULT_T0_ISO,
  etaHoursToFilmNm,
  formatFilmClockLine,
  rebaseIso,
} from "../engine/voyageClock.js";
import { canLeadWithVoice, isSpeaking, stopSpeaking, waitForVoices, voiceEndKind, voiceMayLead, VOICE_LEAD_MS, VOICE_MS_PER_CHAR } from "../utils/speak.js";
import { EventBubbleGate, FilmEventScoreGate, filmEventCard, pickFilmEvent, publishEventBubble } from "../components/eventBubble.js";
import { isAirLegNames } from "../utils/berryLegs.js";
import { filmShownEstimateSeconds, filmVariantAbsent } from "../engine/playSpeeds.js";
import { exitDocumentFullscreen } from "../utils/cinemaHotkey.js";
import { restoreFollowView } from "./useFilmCamera.js";
import { nextFilmWebContext, publicFilmWebContext } from "../utils/filmWebSources.js";
import { publicFilmReceipt } from "../utils/filmReceipt.js";

const API = import.meta.env?.VITE_API_URL ?? "";

export function chapterHasLeg(ch) {
  return [ch?.fromLat, ch?.fromLon, ch?.toLat, ch?.toLon].every((n) => (
    n != null && n !== "" && Number.isFinite(Number(n))
  ));
}

/** Script remote : on garde le texte serveur ; lat/lon manquants viennent du local. */
/** Le script distant ne vaut que s'il porte l'année du t0 demandé. */
/**
 * Ligne d'état Suivre : mêmes milles et heures de mer (durées réelles),
 * date civile décalée vers le t0 choisi. Identité si t0 = départ officiel.
 * Ne touche pas au t0 Simulation.
 */
export function followClockLineFromT0({
  sailNm,
  seaHours,
  iso,
  fromT0 = DEFAULT_T0_ISO,
  t0 = DEFAULT_T0_ISO,
  lang = "fr",
} = {}) {
  return formatFilmClockLine({
    sailNm,
    seaHours,
    iso: rebaseIso(iso, fromT0, t0),
    lang,
  });
}

/** ETA / restants : heures d'horloge, indépendantes du t0 Simulation. */
export function followEtaFromClock(clock, fromFilmNm, toFilmNm, { atQuay = false } = {}) {
  return etaHoursToFilmNm(clock, fromFilmNm, toFilmNm, { atQuay });
}

export function filmTextHasT0Year(chapters, t0) {
  const year = new Date(t0 || "").getUTCFullYear();
  if (!Number.isFinite(year)) return true;
  const text = String(chapters?.[0]?.text || "");
  if (!text) return false;
  return text.includes(String(year));
}

const RE7_STALE = /Bay of Biscay|milles nautiques du départ|station croisée\s*:\s*Station croisée|Aucun port d'entr[ée]e|entrée dans Entrée dans/i;
/** Ces tournures sont un script cassé, même s'il a l'ouverture du voyage. */
const RE7_HARD_STALE = /milles nautiques du départ|station croisée\s*:\s*Station croisée|Aucun port d'entr[ée]e|entrée dans Entrée dans/i;

/** Au-delà : ready seulement avec l'empreinte RG6/RG7 (intégral long). */
export const FILM_READY_MAX_WORDS = 800;

const RG6_OPENING = /Berry-Mappemonde quitte|L['’]expédition Berry-Mappemonde|Berry-Mappemonde leaves|The Berry-Mappemonde expedition/i;
const RG6_MILES_DAYS = /milles|jours de mer|days at sea|\bmiles\b/i;
const RG7_CLOSE = /Aujourd['’]hui, le bateau|Today, the boat/i;

export function filmWordCount(text) {
  return (String(text || "").match(/\S+/g) || []).length;
}

/** Ouverture RG6/RG7 + milles/jours, ou clôture « Aujourd'hui, le bateau ». */
export function filmHasRg6Rg7Fingerprint(text) {
  const blob = String(text || "");
  if (RG7_CLOSE.test(blob)) return true;
  return RG6_OPENING.test(blob) && RG6_MILES_DAYS.test(blob);
}

export function isRe7OfficialFilm(data) {
  const chapters = data?.chapters || [];
  if (!chapters.length) return false;
  const blob = chapters.map((c) => c.text || "").join(" ");
  if (RE7_HARD_STALE.test(blob)) return false;
  // « Bay of Biscay » tout seul est un vieux script. Dans le film actuel,
  // le golfe est une étape réelle, à côté de l'ouverture et de « Today, the boat ».
  if (/Bay of Biscay/i.test(blob) && !filmHasRg6Rg7Fingerprint(blob)) return false;
  if (RE7_STALE.test(blob) && !filmHasRg6Rg7Fingerprint(blob)) return false;
  if (filmWordCount(blob) <= FILM_READY_MAX_WORDS) return true;
  return filmHasRg6Rg7Fingerprint(blob);
}

/** pending | ready | stale | empty | absent | preparing */
export function officialFilmStatus(data, { fetchFailed = false } = {}) {
  if (fetchFailed) return "absent";
  if (isPreparingFilm(data)) return "preparing";
  if (isRe7OfficialFilm(data)) return "ready";
  if (data?.chapters?.length) return "stale";
  if (data == null) return "pending";
  return "empty";
}

/** Officiel : /voyage/official/film. Suivre × ma route : /voyage/{id}/film. */
export function filmRequestPath(voyageId) {
  const id = String(voyageId || "").trim();
  if (id && id !== "official") return `/voyage/${encodeURIComponent(id)}/film`;
  return "/voyage/official/film";
}

/** Contrat RG11A : source du rédigé Super servi par le stock. */
export const WRITTEN_FILM_SOURCE = "nemotron-super-token-factory";

export function filmRequestStyle(filmStyle) {
  return filmStyle === "written" ? "written" : "raw";
}

export function isWrittenFilmSource(source) {
  const s = String(source || "").toLowerCase();
  if (s === WRITTEN_FILM_SOURCE || s === "nemotron-super" || s === "nemotron") return true;
  return s.includes("nemotron") && (s.includes("super") || s.includes("token-factory"));
}

const FILM_SOURCE_I18N = Object.freeze({
  "nemotron-nano": "storySourceNano",
  "nemotron-lightning": "storySourceLightning",
  "nemotron-super": "storySourceSuper",
  "nemotron-super-token-factory": "storySourceSuper",
  "nemotron-super-vl": "storySourceSuperVl",
  "nemotron-ultra": "storySourceUltra",
  nemotron: "storySourceSuper",
  openrouter: "storySourceOpenrouter",
  claude: "storySourceClaude",
  rules: "storySourceRules",
  budget: "storySourceBudget",
  cache: "storySourceCache",
});

/** Super 120B (retired 9 Nov. 2026) only when the served model id names it. */
function isLegacySuperModelId(model) {
  const m = String(model || "").toLowerCase();
  return m.includes("super") && m.includes("120b");
}

/**
 * Libellé du film. Le palier write sert Nemotron 3.5 Super VL (llm_budget.DEFAULT_MODELS) :
 * une source « nemotron-super » sans modèle se lit Super VL ; `model` (id servi) tranche
 * (Super 120B ancien stock, Lightning en repli étiqueté).
 */
export function filmSourceKey(source, reviewedBy, model) {
  const s = String(source || "").toLowerCase();
  const m = String(model || "").toLowerCase();
  const reviewed = String(reviewedBy || "").toLowerCase();
  const legacy = isLegacySuperModelId(m) || isLegacySuperModelId(s);
  if ((s.includes("reviewed") && s.includes("ultra")) || (reviewed.includes("ultra") && isWrittenFilmSource(source))) {
    return legacy ? "storySourceSuper120bReviewed" : "storySourceSuperReviewed";
  }
  if (s === "openrouter" || s.startsWith("openrouter")) return "storySourceOpenrouter";
  if (s === "claude" || s.startsWith("claude")) return "storySourceClaude";
  if (/gpt-oss|nvidia-gpt|\bnim\b/.test(s) || s.startsWith("nvidia-")) return "storySourceNim";
  if (legacy) return "storySourceSuper120b";
  if (s.endsWith("-nano") || s.includes("-nano")) return "storySourceNano";
  if (s.includes("super-vl")) return "storySourceSuperVl";
  if (isWrittenFilmSource(source)) {
    if (m.includes("lightning")) return "storySourceLightning";
    if (m.includes("nemotron") && m.includes("ultra")) return "storySourceUltra";
    return "storySourceSuper";
  }
  return FILM_SOURCE_I18N[s] || "storySourceRules";
}

/**
 * Contrat RG11A : style=written + hasWritten → rédigé (source Super, ancres
 * du plan servi) ; style=written + !hasWritten → brut, et on le dit ;
 * style=raw → brut, le hasWritten du payload est ignoré (le brut le pose
 * toujours à false).
 */
export function resolveServedFilm(data, requestedStyle) {
  const askedWritten = requestedStyle === "written";
  // Écart n° 43 : provenance web rangée par le serveur au clic Rédigé (port, liens), quel que soit le style.
  const webContext = publicFilmWebContext(data);
  if (askedWritten) {
    const hasWritten = Boolean(data?.hasWritten);
    if (hasWritten) {
      return {
        updateHasWritten: true,
        hasWritten: true,
        effectiveStyle: "written",
        source: data?.source || WRITTEN_FILM_SOURCE,
        reviewedBy: data?.reviewedBy || "",
        model: data?.model || "",
        applyPlan: true,
        webContext,
        receipt: publicFilmReceipt(data),
      };
    }
    return {
      updateHasWritten: true,
      hasWritten: false,
      effectiveStyle: "raw",
      source: "rules",
      reviewedBy: "",
      model: "",
      applyPlan: true,
      webContext,
    };
  }
  return {
    updateHasWritten: false,
    hasWritten: null,
    effectiveStyle: "raw",
    reviewedBy: "",
    model: "",
    source: data?.source || "rules",
    applyPlan: true,
    webContext,
  };
}

export function writtenPillEnabled(hasWritten, opts) {
  const flags = hasWritten && typeof hasWritten === "object"
    ? hasWritten
    : opts;
  if (flags?.customFilm) return false;
  return true;
}

export function filmResponseShouldRetry(status) {
  return Number(status) !== 405;
}

export function isOfficialFilmVoyage(voyageId) {
  const id = String(voyageId || "").trim();
  return !id || id === "official";
}

export function isPreparingFilm(data) {
  return String(data?.status || "").toLowerCase() === "preparing";
}

/**
 * Film jouable : empreinte RE7 pour Berry ; pour ma route, le status
 * serveur `ready` + des chapitres (jamais le brut local).
 */
export function isReadyRemoteFilm(data, { official = true } = {}) {
  if (!data || isPreparingFilm(data)) return false;
  if (official) return isRe7OfficialFilm(data);
  return String(data.status || "").toLowerCase() === "ready" && Boolean(data.chapters?.length);
}

/** Tant que le serveur répond preparing, relire toutes les 10 s. */
export const FILM_PREPARE_POLL_MS = 10_000;

/**
 * Revoir en Suivre : horloge officielle + /film RE7 de ce checkout.
 * absent / pending / stale / empty : pas de repli Simulation (plus de
 * récit La Rochelle → Ajaccio sur un HTTP 500).
 */
export function canStartOfficialReplay({
  requireOfficialFilm = true,
  officialClock = null,
  fallbackClock = null,
  remoteStatus = "pending",
} = {}) {
  if (!requireOfficialFilm) return Boolean(officialClock || fallbackClock);
  if (remoteStatus === "ready") return Boolean(officialClock);
  return false;
}

export function pickFilmChapters(remote, local, fallback = []) {
  const r = remote?.chapters || [];
  const l = local?.chapters || [];
  if (r.length) {
    return {
      chapters: r.map((ch) => {
        if (chapterHasLeg(ch)) return ch;
        const src = l.find((c) => c.id && c.id === ch.id)
          || l.find((c) => c.fromName && ch.fromName && c.fromName === ch.fromName && c.toName === ch.toName);
        return src && chapterHasLeg(src)
          ? { ...ch, fromLat: src.fromLat, fromLon: src.fromLon, toLat: src.toLat, toLon: src.toLon }
          : ch;
      }),
      source: remote.source || "rules",
      remote: true,
    };
  }
  if (l.length) return { chapters: l, source: local.source || "rules", remote: false };
  return { chapters: fallback, source: "rules", remote: false };
}

/** onend immédiat sans boundary : une relance, puis linéaire, film non terminé. */
export function voiceLeadPolicy({
  hadBoundary,
  elapsedMs,
  alreadyRetried,
  chapterIdx = 0,
  chapterCount = 1,
  hasMoreChunks = false,
} = {}) {
  const kind = voiceEndKind({ hadBoundary, elapsedMs, alreadyRetried, hasMoreChunks });
  if (kind === "retry") return { mode: "retry", finish: false, chapterIdx };
  if (kind === "linear") return { mode: "linear", finish: false, chapterIdx };
  const last = chapterIdx + 1 >= chapterCount;
  return { mode: "advance", finish: last && !hasMoreChunks, chapterIdx: last ? chapterIdx : chapterIdx + 1 };
}

/**
 * Caméra live (Polynésie) seulement si le film est vraiment fini
 * ou si le porteur a cliqué Stop — jamais sur un incident de voix.
 */
export function shouldReturnToLive({ userStopped = false, filmFinished = false, voiceIncident = false } = {}) {
  if (voiceIncident && !userStopped && !filmFinished) return false;
  return Boolean(userStopped || filmFinished);
}

/** Avance linéaire : le dernier chapitre est atteint à la durée parlée, pas avant. */
/** Pas de frontière 2 s après le début d’un chapitre : synthèse considérée absente (RG9 / E2). */
export const FILM_VOICE_STALL_MS = 2000;
/** Onglet caché → reprise : le bateau rejoint la voix en au plus 2 s, sans saut (RG9 / E3). */
export const FILM_VISIBILITY_CATCHUP_MS = 2000;

/**
 * Une voix vivante, ce sont des mots. `speaking` (Chrome le laisse
 * à vrai alors que onend/onboundary se sont tus) et un hold ne comptent
 * pas. Un silence court pendant que les frontières arrivent encore ne
 * bascule pas. Sans mot depuis `stallMs` (ou `leadMs` avant le premier),
 * le film lâche cette voix.
 */
export function voiceStalled({
  chapterAgeMs = 0,
  sinceBoundaryMs = Infinity,
  speaking: _speaking = false,
  hold: _hold = false,
  stallMs = FILM_VOICE_STALL_MS,
  leadMs = VOICE_LEAD_MS,
} = {}) {
  const stall = Number.isFinite(Number(stallMs)) ? Number(stallMs) : FILM_VOICE_STALL_MS;
  const lead = Number.isFinite(Number(leadMs)) ? Number(leadMs) : VOICE_LEAD_MS;
  const since = Number(sinceBoundaryMs);
  const noWordYet = !Number.isFinite(since);
  if (!noWordYet && since <= stall) return false;
  const wait = noWordYet ? Math.max(stall, lead) : stall;
  return Number(chapterAgeMs) >= wait;
}

/** Caractères déjà atteints (chapitres précédents + index local). */
export function spokenCharsSoFar(plan, chapterIdx, charIdx) {
  const list = plan?.chapters || [];
  const idx = Math.max(0, Number(chapterIdx) || 0);
  let acc = 0;
  for (let i = 0; i < idx && i < list.length; i += 1) {
    acc += Math.max(0, Number(list[i].chars) || String(list[i].text || "").length || 0);
  }
  return acc + Math.max(0, Number(charIdx) || 0);
}

/** Elapsed linéaire pour reprendre au caractère déjà atteint, ~60 ms / car. */
export function voiceContinueElapsed(charReached, msPerChar = VOICE_MS_PER_CHAR) {
  const ms = Number.isFinite(Number(msPerChar)) && Number(msPerChar) > 0
    ? Number(msPerChar)
    : VOICE_MS_PER_CHAR;
  return (Math.max(0, Number(charReached) || 0) * ms) / 1000;
}

/**
 * Lâche la voix et calcule l'horloge linéaire au caractère atteint.
 * Pas de finish(), pas de retour au live.
 */
export function abandonVoiceToLinear({
  plan,
  chapterIdx = 0,
  charIdx = 0,
  msPerChar = VOICE_MS_PER_CHAR,
} = {}) {
  const reached = spokenCharsSoFar(plan, chapterIdx, charIdx);
  const elapsed = voiceContinueElapsed(reached, msPerChar);
  const ms = Number.isFinite(Number(msPerChar)) && Number(msPerChar) > 0
    ? Number(msPerChar)
    : VOICE_MS_PER_CHAR;
  return { reached, elapsed, cps: 1000 / ms };
}

/**
 * Fin du film — quand la voix mène (ou parle encore), seul
 * voiceSpokenAll termine ; le budget n'arrête jamais la clôture au milieu
 * (« Aujourd'hui, le » coupé, transcription du 14 oct.).
 */
/**
 * Index de caractère publié au tick de fin : la fin du dernier chapitre,
 * pour que le sous-titre montre la phrase de clôture et non la 1re phrase.
 */
export function filmEndCharIdx(lastChapter, chapterIdx, chapterCount, fallback = 0) {
  if (!lastChapter || chapterIdx !== chapterCount - 1) return fallback;
  const chars = Number(lastChapter.chars);
  return Number.isFinite(chars) && chars > 0 ? Math.max(fallback, chars) : fallback;
}

export function filmShouldFinish({
  voiceClock = false,
  speaking = false,
  voiceAllDone = false,
  linearFinish = false,
  lastReached = false,
  stopping = false,
} = {}) {
  if (stopping) return false;
  if (voiceAllDone) return true;
  if (voiceClock || speaking) return false;
  return Boolean(linearFinish && lastReached);
}

/**
 * Tant que l'énoncé du chapitre courant n'est pas fini, le playhead
 * reste dans [tA, tB − ε]. La barre lit les marques à tMs, pas chapterIdx :
 * un ingest linéaire au-delà de tB affiche déjà la jambe suivante.
 */
export const FILM_CHAPTER_HOLD_EPS_MS = 1;
/** Marge sous le seuil 0.05 nm de chapterAtNm : la barre reste sur cette jambe. */
export const FILM_CHAPTER_HOLD_NM = 0.08;

function holdPlayheadBeforeNm(clock, tA, t, capNm) {
  const at = positionAt(clock, t);
  const nm = at?.sailNm ?? at?.filmNm;
  if (!Number.isFinite(nm) || nm <= capNm) return t;
  let lo = Number.isFinite(tA) ? tA : t;
  let hi = t;
  for (let i = 0; i < 20; i += 1) {
    const mid = (lo + hi) / 2;
    const m = positionAt(clock, mid)?.sailNm ?? positionAt(clock, mid)?.filmNm;
    if (!Number.isFinite(m) || m > capNm) hi = mid;
    else lo = mid;
  }
  return lo;
}

/** Playhead au plafond de jambe : l'horloge des caractères ne doit plus attendre tB. */
export function filmChapterPlayheadCapped({ t, chapter, clock = null } = {}) {
  const published = filmTimeWhileChapterSpeaks({ t, chapter, hold: true, clock });
  const cap = filmTimeWhileChapterSpeaks({
    t: Number(chapter?.tB),
    chapter,
    hold: true,
    clock,
  });
  const atCap = Number.isFinite(published) && Number.isFinite(cap) && published + 1 >= cap;
  return { t: published, atCap };
}

/**
 * RC52 : instant du bateau pour un charIdx de phrase.
 * Tant que la phrase n'est pas finie : `timeAt(charIdx)`, jamais tB
 * (ancre de fin de chapitre) ni un t déjà à l'arrivée / « aujourd'hui ».
 */
export function filmBoatTimeAtPhrase({
  chapter,
  charIdx = 0,
  plan = null,
  chapterIdx = 0,
  phraseEnded = false,
  t = null,
} = {}) {
  const sent = sentenceSpan(chapter, charIdx);
  const idx = Number.isFinite(Number(chapterIdx)) ? Number(chapterIdx) : (chapter?.idx ?? 0);
  const phraseT = plan?.timeAt ? plan.timeAt(idx, charIdx) : sent.startT;
  const tB = chapterTimeMs(chapter?.tB);
  const lastSentence = !chapter
    || sent.end + 1e-6 >= (Number(chapter.chars) || sent.end);
  if (!phraseEnded) {
    let next = Number.isFinite(phraseT) ? phraseT : sent.startT;
    if (Number.isFinite(sent.endT)) next = Math.min(next, sent.endT);
    if (!lastSentence && Number.isFinite(tB) && Number.isFinite(next)) {
      next = Math.min(next, tB - FILM_CHAPTER_HOLD_EPS_MS);
    }
    return next;
  }
  let next = Number.isFinite(Number(t)) ? Number(t) : (Number.isFinite(phraseT) ? phraseT : sent.endT);
  if (Number.isFinite(sent.endT) && Number.isFinite(next) && next < sent.endT) {
    next = sent.endT;
  }
  if (Number.isFinite(tB) && Number.isFinite(next)) next = Math.min(next, tB);
  return next;
}

/** Position rendue : `positionAt(clock, instant de la phrase)`. */
export function filmBoatAtPhrase({
  clock,
  chapter,
  charIdx,
  plan,
  chapterIdx,
  phraseEnded,
  t,
} = {}) {
  const when = filmBoatTimeAtPhrase({
    chapter, charIdx, plan, chapterIdx, phraseEnded, t,
  });
  return { t: when, pos: positionAt(clock, when) };
}

/** Playhead publié tant que la voix / le sous-titre finit la phrase. */
function chapterTimeMs(v) {
  if (v == null || v === "") return NaN;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const parsed = Date.parse(v);
  if (Number.isFinite(parsed)) return parsed;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
}

export function filmTimeWhileChapterSpeaks({
  t,
  chapter,
  hold = false,
  clock = null,
} = {}) {
  const tA = chapterTimeMs(chapter?.tA);
  const tB = chapterTimeMs(chapter?.tB);
  let next = Number(t);
  if (!Number.isFinite(next)) next = Number.isFinite(tA) ? tA : 0;
  if (Number.isFinite(tA)) next = Math.max(tA, next);
  if (Number.isFinite(tB)) next = Math.min(tB, next);
  if (!hold) return next;
  if (Number.isFinite(tA) && Number.isFinite(tB) && tB > tA) {
    next = Math.min(next, Math.max(tA, tB - FILM_CHAPTER_HOLD_EPS_MS));
  }
  if (clock && Number.isFinite(tB)) {
    const dest = positionAt(clock, tB);
    const destNm = dest?.sailNm ?? dest?.filmNm;
    if (Number.isFinite(destNm) && Number.isFinite(tA)) {
      next = holdPlayheadBeforeNm(clock, tA, next, destNm - FILM_CHAPTER_HOLD_NM);
      if (Number.isFinite(tA)) next = Math.max(tA, next);
      if (Number.isFinite(tB)) next = Math.min(tB, next);
    }
  }
  return next;
}

/**
 * ApplyChapter depuis l'horloge linéaire seulement si la voix
 * ne mène pas et ne parle pas (y compris entre deux phrases). Le chemin
 * voix applique le chapitre suivant depuis onEnd.
 */
export function shouldApplyChapterFromClock({
  voiceClock = false,
  speaking = false,
} = {}) {
  return !voiceClock && !speaking;
}

/** Part du récit déjà dite (0..1) : caractères prononcés / caractères du film. */
export function spokenProgress(plan, chapterIdx, charIdx) {
  const list = plan?.chapters || [];
  const total = list.reduce((s, c) => s + (Number(c.chars) || 0), 0);
  if (!total) return 0;
  const i = Math.max(0, Math.min(list.length - 1, Number(chapterIdx) || 0));
  let before = 0;
  for (let k = 0; k < i; k += 1) before += Number(list[k].chars) || 0;
  const cur = Math.max(0, Math.min(Number(list[i]?.chars) || 0, Number(charIdx) || 0));
  return Math.max(0, Math.min(1, (before + cur) / total));
}

export function linearFilmAt(elapsed, plan, cps = FILM_ESTIMATE_CPS) {
  const t = Number(elapsed) || 0;
  const total = filmSpeakChars(plan);
  const rate = Number(cps) > 0 ? Number(cps) : FILM_ESTIMATE_CPS;
  const speakSec = total > 0 ? total / rate : (Number(plan?.targetSeconds) || 0);
  const spoken = total > 0 ? Math.min(total, Math.max(0, t) * rate) : 0;
  const ch = total > 0 ? chapterAtSpokenChars(plan, spoken) : chapterAtElapsed(plan, t);
  const lastIdx = Math.max(0, (plan?.chapters?.length || 1) - 1);
  const lastReached = (ch?.idx ?? 0) >= lastIdx;
  const allSpoken = total <= 0 || t + 1e-6 >= speakSec;
  return {
    chapterIdx: ch?.idx ?? 0,
    charIdx: ch?.localCharIdx ?? 0,
    finish: speakSec > 0 && t >= speakSec && lastReached && allSpoken,
    lastReached,
  };
}

/** ~ FILM_BUDGET_CHARS / 150 s : la voix ne meuble pas, le temps suit le texte. */
export const FILM_CHARS_PER_SECOND = 16;
/** Débit d'estimation = débit vocal constant depuis le 27 sept. Pas de recalibrage. */
export const FILM_ESTIMATE_CPS = 15;

/**
 * RC41 : index écrit du sous-titre. Si la voix mène, le texte avance à
 * FILM_ESTIMATE_CPS dès la première phrase — jamais un sprint au budget
 * (linearChar) puis un calage. Sans voix : la même constante, un seul régime.
 */
export function filmScriptCharIdx({
  voiceClock = false,
  phraseOn = false,
  phraseEnded = false,
  phraseChar0 = 0,
  phraseElapsedS = 0,
  sentenceEndChar = Infinity,
  chapterChars = Infinity,
  linearChar = 0,
  cps = FILM_ESTIMATE_CPS,
} = {}) {
  if (!voiceClock) return Math.max(0, Number(linearChar) || 0);
  const start = Math.max(0, Number(phraseChar0) || 0);
  const capSent = Number.isFinite(Number(sentenceEndChar)) ? Number(sentenceEndChar) : Infinity;
  const capCh = Number.isFinite(Number(chapterChars)) && Number(chapterChars) > 0
    ? Number(chapterChars)
    : Infinity;
  const cap = Math.min(capSent, capCh);
  if (!phraseOn) return Math.min(start, Number.isFinite(cap) ? cap : start);
  if (phraseEnded) return Number.isFinite(cap) ? cap : start;
  const rate = Number(cps) > 0 ? Number(cps) : FILM_ESTIMATE_CPS;
  const pred = start + rate * Math.max(0, Number(phraseElapsedS) || 0);
  return Math.max(0, Number.isFinite(cap) ? Math.min(pred, cap) : pred);
}

/** Deux débits écrits (car/s) : écart relatif < 20 % (parcours #467). */
export function filmCharRatesStable(rateA, rateB, maxRel = 0.2) {
  const a = Number(rateA);
  const b = Number(rateB);
  if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0) return false;
  return Math.abs(a - b) / Math.max(a, b) < maxRel;
}

export function filmSpeakChars(plan) {
  const listed = Number(plan?.totalChars);
  if (Number.isFinite(listed) && listed > 0) return listed;
  return (plan?.chapters || []).reduce(
    (s, c) => s + (Number(c.chars) || String(c?.text || "").length || 0),
    0,
  );
}

export function wallClockSpeakSeconds(plan, cps = FILM_ESTIMATE_CPS) {
  const chars = filmSpeakChars(plan);
  const rate = Number(cps) > 0 ? Number(cps) : FILM_ESTIMATE_CPS;
  if (chars > 0 && rate > 0) return chars / rate;
  return Number(plan?.targetSeconds) || 0;
}

export function chapterAtSpokenChars(plan, spokenChars) {
  const list = plan?.chapters || [];
  if (!list.length) return null;
  let acc = 0;
  const x = Math.max(0, Number(spokenChars) || 0);
  for (const ch of list) {
    const n = Math.max(1, Number(ch.chars) || String(ch.text || "").length || 1);
    if (x < acc + n - 1e-9) {
      return { ...ch, localCharIdx: x - acc };
    }
    acc += n;
  }
  const last = list[list.length - 1];
  return { ...last, localCharIdx: Math.max(1, Number(last.chars) || 1) };
}

export function visibilityCatchupStep({
  fromT,
  toT,
  elapsedMs = 0,
  durationMs = FILM_VISIBILITY_CATCHUP_MS,
} = {}) {
  const from = Number(fromT);
  const to = Number(toT);
  const d = Math.max(1, Number(durationMs) || FILM_VISIBILITY_CATCHUP_MS);
  const u = Math.max(0, Math.min(1, (Number(elapsedMs) || 0) / d));
  const e = 1 - (1 - u) * (1 - u);
  const fallback = Number.isFinite(to) ? to : from;
  const t = Number.isFinite(from) && Number.isFinite(to)
    ? from + (to - from) * e
    : fallback;
  return { t, u, done: u >= 1 };
}

export function filmSpeakSeconds(chapters) {
  const chars = (chapters || []).reduce((s, c) => s + String(c?.text || "").length, 0);
  return Math.max(1, Math.round(chars / FILM_CHARS_PER_SECOND));
}

export function filmEstimatedSeconds(chars, cps = FILM_ESTIMATE_CPS) {
  const n = Number(chars) || 0;
  if (n <= 0) return 0;
  const rate = Number(cps) > 0 ? Number(cps) : FILM_ESTIMATE_CPS;
  return Math.max(1, Math.round(n / rate));
}

export function formatFilmEstimateClock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (!s) return "";
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function pickFilmEstimateSeconds(targetSeconds, estimates, fallbackSeconds = 0) {
  return filmShownEstimateSeconds(targetSeconds, estimates, fallbackSeconds);
}

export function replayPlace(active, live) {
  if (!active || !live) return null;
  const lat = Number(live.lat);
  const lon = Number(live.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon };
}

/** Pendant le film, le briefing suit la position rejouée ; au Stop, retour à maintenant. */
export function briefingForReplayPosition({
  active = false,
  live = null,
  nowBriefing = "",
  replayText = "",
} = {}) {
  if (!active) return { view: "suivre", briefing: nowBriefing, follows: false };
  const place = replayPlace(true, live);
  const text = String(replayText || "").trim();
  if (!place || !text) {
    return { view: "suivre", briefing: "", follows: false, hidden: true };
  }
  return { view: "suivre", briefing: text, follows: true, lat: place.lat, lon: place.lon };
}

/** Même requête seulement. Une autre durée (seconds) recharge le texte. */
export function filmQueryKeepsReady(prev, next) {
  if (!prev || !next) return false;
  return String(prev) === String(next);
}

/**
 * Durée cochée : refuser un texte dont la lecture dépasse 1,5 × le budget.
 * Aucune durée cochée (0) : le journal intégral peut partir.
 */
export function filmBudgetCanPlay({
  chars = 0, budgetSeconds = 0, cps = FILM_ESTIMATE_CPS,
} = {}) {
  const budget = Number(budgetSeconds) || 0;
  if (budget <= 0) return true;
  const n = Number(chars) || 0;
  if (n <= 0) return true;
  const rate = Number(cps) > 0 ? Number(cps) : FILM_ESTIMATE_CPS;
  return n / rate <= budget * 1.5;
}

function filmPayloadChars(data) {
  const chapters = Array.isArray(data?.chapters) ? data.chapters : [];
  const fromText = chapters.reduce((n, c) => n + String(c?.text || "").length, 0);
  if (fromText > 0) return fromText;
  return Number(data?.chars) || 0;
}

/** Durée cochée → budget ; aucune → le temps que prend le journal. */
export function resolveFilmTargetSeconds(selected, chapters) {
  const n = Number(selected);
  if (Number.isFinite(n) && n > 0) return n;
  return filmSpeakSeconds(chapters);
}

/** Re-clic sur la même durée = décoché (0). */
export function toggleFilmDuration(current, clicked) {
  const a = Number(current);
  const b = Number(clicked);
  if (Number.isFinite(a) && Number.isFinite(b) && a === b) return 0;
  return Number.isFinite(b) && b > 0 ? b : 0;
}

/** Budget coché : on attend la fin du budget, même si la voix a fini (KO #302). */
export function shouldHoldFilmForBudget({
  userBudget = 0, wallElapsed = 0, lastChapter = false,
} = {}) {
  return Boolean(lastChapter) && Number(userBudget) > 0 && Number(wallElapsed) < Number(userBudget);
}

export const APPROACH_FRAC = 0.8;

/**
 * Stop du film : coupe la voix, libère la caméra (fin de
 * `filmActive` + `publishFilmEnd`), annule la boucle. L'appelant remet
 * `active=false` — MapSceneController quitte alors le suivi film.
 */
/** Dernière phrase de clôture, pour qu'elle reste lisible après l'arrêt (ligne tronquée). */
export function closingSubtitle(text) {
  const parts = String(text || "").split(/(?<=[.!?…])\s+/).filter(Boolean);
  const last = parts[parts.length - 1] || "";
  if (/aujourd|today/i.test(last)) return last;
  return String(text || "");
}

/** Phrases avion RF5 déjà présentes dans le chapitre — on ne les invente pas. */
export const FILM_AIR_PHRASE_RE =
  /prend l['’]avion pour|s['’]envole|the crew flies(?: to| from)|retour en avion vers|return flight to/i;

const FILM_AIR_SENTENCE_RE =
  /[^.!?…\n]*?(?:prend l['’]avion pour|s['’]envole|the crew flies(?: to| from)|retour en avion vers|return flight to)[^.!?…]*(?:[.!?…]|$)/gi;

const FILM_AIR_OUT_PHRASE_RE =
  /s['’]envole de Cayenne|prend l['’]avion pour Halifax|flies from Cayenne|the crew flies to Halifax/i;

const FILM_AIR_BACK_PHRASE_RE =
  /s['’]envole (?:de |d['’])Halifax|prend l['’]avion pour Cayenne|flies from Halifax|retour en avion vers Cayenne|return flight to Cayenne/i;

function collectAirSentences(text) {
  const found = String(text || "").match(FILM_AIR_SENTENCE_RE) || [];
  const parts = [];
  const seen = new Set();
  for (const piece of found) {
    const s = piece.trim();
    if (!s) continue;
    const key = s.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(s);
  }
  return parts;
}

function airPhraseMatchesLeg(sentence, fromName, toName) {
  const outbound = /cayenne/i.test(String(fromName || "")) && /halifax/i.test(String(toName || ""));
  if (outbound) return FILM_AIR_OUT_PHRASE_RE.test(sentence) && !FILM_AIR_BACK_PHRASE_RE.test(sentence);
  return FILM_AIR_BACK_PHRASE_RE.test(sentence) && !FILM_AIR_OUT_PHRASE_RE.test(sentence);
}

/**
 * Ligne visible du sous-titre : phrases avion du chapitre
 * vol Cayenne↔Halifax seulement. Un chapitre side / reprise n'est jamais
 * remplacé par le bloc des deux vols.
 */
export function visibleFilmSubtitle(text, opts = {}) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  const fromName = opts.fromName;
  const toName = opts.toName;
  const named = (fromName != null && fromName !== "") || (toName != null && toName !== "");
  if (named && !isAirLegNames(fromName, toName)) return raw;
  if (!FILM_AIR_PHRASE_RE.test(raw)) return raw;
  const parts = collectAirSentences(raw);
  if (!parts.length) return raw;
  if (named && isAirLegNames(fromName, toName)) {
    const kept = parts.filter((s) => airPhraseMatchesLeg(s, fromName, toName));
    return kept.length ? kept.join(" ") : "";
  }
  return parts.join(" ");
}

export function filmSubtitleShowsAir(text) {
  return FILM_AIR_PHRASE_RE.test(String(text || ""));
}

export function splitFilmSentences(text, starts) {
  const raw = String(text || "");
  if (!raw) return [];
  const given = Array.isArray(starts)
    ? starts.map(Number).filter((n) => Number.isFinite(n) && n >= 0).sort((a, b) => a - b)
    : [];
  if (given.length) {
    const out = [];
    for (let i = 0; i < given.length; i += 1) {
      const a = given[i];
      const b = i + 1 < given.length ? given[i + 1] : raw.length;
      const piece = raw.slice(a, b);
      if (piece.trim()) out.push({ start: a, text: piece.trim() });
    }
    return out;
  }
  const parts = raw.split(/(?<=[.!?…])\s+/).filter(Boolean);
  const out = [];
  let from = 0;
  for (const p of parts) {
    const at = raw.indexOf(p, from);
    const start = at >= 0 ? at : from;
    out.push({ start, text: p });
    from = start + p.length;
  }
  return out;
}

export function filmSentenceAt(text, charIdx, starts) {
  const sentences = splitFilmSentences(text, starts);
  if (!sentences.length) return { start: 0, text: String(text || "") };
  const x = Math.max(0, Number(charIdx) || 0);
  let cur = sentences[0];
  for (const s of sentences) {
    if (x >= s.start) cur = s;
    else break;
  }
  return cur;
}

function spokenPlaceName(name) {
  return String(name || "").replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
}

export function filmPlaceInSentence(sentence, {
  fromName = "",
  toName = "",
  anchors = [],
  charIdx = 0,
} = {}) {
  const text = sentence?.text || "";
  const origin = Number(sentence?.start) || 0;
  const names = [];
  const push = (n) => {
    const s = spokenPlaceName(n);
    if (s && s.length >= 2 && !names.includes(s)) names.push(s);
  };
  push(toName);
  push(fromName);
  for (const a of anchors || []) {
    if (a?.name) push(a.name);
    if (a?.place) push(a.place);
  }
  names.sort((a, b) => b.length - a.length);
  const x = Math.max(0, Number(charIdx) || 0);
  for (const name of names) {
    const at = text.indexOf(name);
    if (at < 0) continue;
    if (x + 1e-9 < origin + at) continue;
    return { name, start: at, end: at + name.length };
  }
  return null;
}

export function filmSubtitleAt(text, charIdx, opts = {}) {
  const starts = opts.sentenceStarts || opts.sentences;
  const sentence = filmSentenceAt(text, charIdx, starts);
  const place = filmPlaceInSentence(sentence, { ...opts, charIdx });
  return {
    sentence: sentence.text,
    start: sentence.start,
    place: place?.name || "",
    placeStart: place?.start ?? -1,
    placeEnd: place?.end ?? -1,
  };
}

/**
 * Ligne de la barre : une phrase dès charIdx=0.
 * Seek et pinned : la phrase sous le curseur, jamais le chapitre entier.
 * Chapitre side / reprise : jamais le bloc avion. Chapitre vol : seulement
 * la phrase avion sous le curseur (un vol). Phrase mer recollée dans un
 * chapitre vol (fusion 2:30) : on la garde.
 */
export function filmBarSubtitle({
  chapterText = "",
  charIdx = 0,
  pinned: _pinned = false,
  sentenceStarts,
  fromName,
  toName,
  anchors,
} = {}) {
  const raw = String(chapterText || "");
  if (!raw) return { text: "", place: "", sentenceMode: false };
  const x = Math.max(0, Number(charIdx) || 0);
  const sub = filmSubtitleAt(raw, x, { sentenceStarts, fromName, toName, anchors });
  const named = Boolean(fromName || toName);
  const airChapter = named && isAirLegNames(fromName, toName);
  if (named && !airChapter) {
    return { text: sub.sentence, place: sub.place, sentenceMode: true };
  }
  if (airChapter && !FILM_AIR_PHRASE_RE.test(sub.sentence)) {
    return { text: sub.sentence, place: sub.place, sentenceMode: true };
  }
  if (airChapter && FILM_AIR_PHRASE_RE.test(sub.sentence)) {
    const one = visibleFilmSubtitle(sub.sentence, { fromName, toName });
    return { text: one || sub.sentence, place: "", sentenceMode: true };
  }
  if (FILM_AIR_PHRASE_RE.test(raw)) {
    const extracted = visibleFilmSubtitle(raw, { fromName, toName });
    if (extracted) return { text: extracted, place: "", sentenceMode: true };
  }
  return { text: sub.sentence, place: sub.place, sentenceMode: true };
}

export function filmSubtitleHighlight(text, place) {
  const raw = String(text || "");
  const name = String(place || "");
  if (!raw || !name) return { before: raw, place: "", after: "" };
  const at = raw.indexOf(name);
  if (at < 0) return { before: raw, place: "", after: "" };
  return { before: raw.slice(0, at), place: name, after: raw.slice(at + name.length) };
}

export function applyReplayStop({
  cancelRaf,
  stopVoice,
  releaseCamera,
  keepChapterText = false,
  chapterText = "",
} = {}) {
  (stopVoice || stopSpeaking)();
  (releaseCamera || publishFilmEnd)();
  cancelRaf?.();
  const kept = keepChapterText ? closingSubtitle(chapterText) : "";
  return {
    active: false,
    tMs: null,
    card: null,
    progress: kept ? 1 : 0,
    chapterIdx: 0,
    chapterText: kept,
    filmLeg: null,
  };
}

function shortStopName(name) {
  return String(name || "").replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
}

function foldArrivalPort(name) {
  return String(name || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/\s*\([^)]*\)\s*/g, " ")
    .replace(/[^a-z0-9]+/gi, " ")
    .trim()
    .toLowerCase();
}

function portFromArrivalText(text) {
  const flat = String(text || "").normalize("NFD").replace(/\p{M}/gu, "").trim();
  const named = /^(?:arrival at|arrivee\s+a)\s+(.+?)(?:\s+on\b|\s+le\b|[.,]|$)/i.exec(flat);
  return named ? foldArrivalPort(named[1]) : "";
}

function arrivalCardPort(card) {
  return portFromArrivalText(card?.title)
    || portFromArrivalText(card?.text)
    || foldArrivalPort(card?.title);
}

function isArrivalBubble(card) {
  if (!card) return false;
  const id = String(card.id || card.key || "");
  if (id.startsWith("approach:")) return true;
  return /arriv/i.test(`${card.title || ""} ${card.text || ""}`);
}

function sameArrivalPort(cardPort, dest) {
  if (!cardPort || !dest) return false;
  if (cardPort === dest) return true;
  return cardPort.startsWith(`${dest} `) || dest.startsWith(`${cardPort} `);
}

/**
 * Une carte d'arrivée ne reste ouverte que pour la destination du chapitre.
 * Halifax pendant Saint-Pierre → Cayenne, ou Papeete pendant Papeete → Mata-Utu,
 * se ferme. On ne cache pas le nom : la carte quitte l'écran.
 */
export function arrivalBubbleFitsDestination(card, toName) {
  if (!isArrivalBubble(card)) return true;
  const port = arrivalCardPort(card);
  const dest = foldArrivalPort(toName);
  if (!port) return true;
  if (!dest) return false;
  return sameArrivalPort(port, dest);
}

/** Bulle à l'approche de l'escale d'arrivée du chapitre (affichage RA3 ; choix R9). */
export function approachStopEvent(chapter, { frac } = {}) {
  const name = shortStopName(chapter?.toName);
  if (!name) return null;
  const f = Number(frac);
  if (!(f >= APPROACH_FRAC)) return null;
  const arrival = String(chapter.text || "")
    .split(/(?<=[.!?])\s+/)
    .filter((s) => /arriv/i.test(s))
    .pop() || "";
  const id = `approach:${chapter.idx}:${name}`;
  return {
    id,
    kind: "stop",
    score: 3,
    card: {
      id,
      key: id,
      kind: "stop",
      title: name,
      text: arrival,
    },
  };
}

/** 60 frames linéaires : positions le long du trait, y compris le dernier chapitre. */
export function stepAlongPlan({ plan, clock, frames = 60, dt = 1 / 60, elapsed0 = 0 } = {}) {
  const positions = [];
  let elapsed = Number(elapsed0) || 0;
  for (let i = 0; i < frames; i++) {
    elapsed += dt;
    const linear = linearFilmAt(elapsed, plan);
    const ch = chapterAtElapsed(plan, elapsed);
    const frac = ch && ch.seconds > 0
      ? Math.max(0, Math.min(1, (elapsed - ch.startWall) / ch.seconds))
      : 1;
    const tMs = ch ? ch.tA + frac * (ch.tB - ch.tA) : plan.timeAt(0, 0);
    const pos = positionAt(clock, tMs);
    positions.push({
      ...(pos || {}),
      chapterIdx: ch?.idx ?? 0,
      tMs,
      finish: linear.finish,
      lastReached: linear.lastReached,
    });
  }
  return positions;
}

/**
 * « Revoir l'expédition » (cinématique F1 / fluide R4) : rejoue la
 * route de Saint-Maur à aujourd'hui. Le temps avance chaque frame ; la voix
 * recale vers timeAt(charIdx) en ≤ 300 ms. Sans voix, avance linéaire
 * continue sur 150 s (ou 180 s). `live` remplace le bateau officiel pendant
 * le film ; à la fin réelle ou sur Stop, retour au live — jamais sur
 * un incident de voix.
 */
export function useReplay({
  clock,
  fallbackClock = null,
  requireOfficialFilm = true,
  journal,
  enabled = false,
  lang = "fr",
  secondsPerDay = DEFAULT_SECONDS_PER_DAY,
  marks = [],
  destination = null,
  t0 = DEFAULT_T0_ISO,
  voyageId = "official",
} = {}) {
  const [active, setActive] = useState(false);
  const [tMs, setTMs] = useState(null);
  const [card, setCard] = useState(null);
  // The voice is piloted by the film-bar Écouter button (no replay-voice).
  const [voice, setVoice] = useState(true);
  const [targetSeconds, setTargetSeconds] = useState(0);
  const [chapterIdx, setChapterIdx] = useState(0);
  const [chapterText, setChapterText] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [subtitlePlace, setSubtitlePlace] = useState("");
  const [filmLeg, setFilmLeg] = useState(null);
  const [voiceRate, setVoiceRate] = useState(1);
  const [progress, setProgress] = useState(0);
  const [filmSource, setFilmSource] = useState("rules");
  const [filmReviewedBy, setFilmReviewedBy] = useState("");
  const [filmModel, setFilmModel] = useState("");
  const [filmWebContext, setFilmWebContext] = useState(null);
  const [filmReceipt, setFilmReceipt] = useState(null);
  const [filmWriting, setFilmWriting] = useState(false);
  const filmWritingRef = useRef(false);
  const filmWriteRequestRef = useRef(null);
  const filmWriteGenerationRef = useRef(0);
  const [filmStyle, setFilmStyle] = useState("raw");
  const [hasWritten, setHasWritten] = useState(false);
  const [filmWriteError, setFilmWriteError] = useState(false);
  const [writtenUnavailable, setWrittenUnavailable] = useState(null);
  const filmWritePollGenRef = useRef(0);
  const filmWritePollAbortRef = useRef(null);
  const filmWriteStartingRef = useRef(false);
  const filmWriteNextStepRef = useRef(async () => "stop");
  // Style du plan chargé (visite des juges, bouton Rédigé) : "written" / "raw" quand le serveur
  // a servi le style demandé, "mismatch" quand il a servi le Brut à une demande Rédigé.
  const [filmLoadedStyle, setFilmLoadedStyle] = useState("");
  const [estimatedSeconds, setEstimatedSeconds] = useState(0);
  const [variantEstimates, setVariantEstimates] = useState(null);
  const [filmParagraphs, setFilmParagraphs] = useState([]);
  const remotePlanRef = useRef(null);
  // Langue et budget du plan chargé : on ne garde le plan « prêt » pendant un rechargement que s'il
  // répond à la MÊME demande — sinon un clic Revoir juste après le passage en anglais jouait le film
  // français (spec rb5 / ra2 en CI, 28 sept.).
  const remotePlanKeyRef = useRef("");
  const [remoteStatus, setRemoteStatus] = useState("pending");
  const [filmLoadAttempt, setFilmLoadAttempt] = useState(0);
  const remoteStatusRef = useRef("pending");
  const setFilmStatus = useCallback((s) => {
    remoteStatusRef.current = s;
    setRemoteStatus(s);
  }, []);
  const pinnedIdxRef = useRef(null);
  const pinnedCharRef = useRef(null);
  const seekChapterRef = useRef(null);
  const queueRef = useRef([]);
  const cardSinceRef = useRef(0);
  const lastTRef = useRef(null);
  const rafRef = useRef(null);
  const timeline = useMemo(() => journalTimeline(journal), [journal]);
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;
  const windowRef = useRef(null);
  const planRef = useRef(null);
  const chapterIdxRef = useRef(0);
  const startWallRef = useRef(0);
  const chapterStartedAtRef = useRef(0);
  const finishedRef = useRef(false);
  const stoppingRef = useRef(false);
  const chapterTextRef = useRef("");
  const finishRef = useRef(() => {});
  const voiceCharRef = useRef(0);
  const voiceFailedRef = useRef(false);
  const voiceSpokenAllRef = useRef(false);
  const voiceBoundaryAtRef = useRef(0);
  const tMsRef = useRef(null);
  const voiceTargetRef = useRef(null);
  const recaleRemainRef = useRef(0);
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const filmBubbleRef = useRef(new EventBubbleGate());
  const filmScoreRef = useRef(new FilmEventScoreGate());
  const publishedBubbleRef = useRef(null);
  const clockRef = useRef(clock);
  if (clock) clockRef.current = clock;
  const budgetRef = useRef(0);
  const lastUiAtRef = useRef(0);
  const hiddenRef = useRef(false);
  const hiddenTRef = useRef(null);
  const hiddenElapsedRef = useRef(0);
  const displayElapsedRef = useRef(0);
  const catchupRef = useRef(null);
  const lastSubtitleRef = useRef("");
  const lastBoundaryCharRef = useRef(0);
  const voicePhraseOnRef = useRef(false);
  const voicePhraseAtRef = useRef(0);
  const voicePhraseChar0Ref = useRef(0);
  const lastBoundaryAtRef = useRef(0);
  const voiceHoldRef = useRef(false);
  const phraseEndedRef = useRef(false);
  const skipRampRef = useRef(null);
  const filmElapsedRef = useRef(0);
  const linearHoldRef = useRef(false);
  const voiceAbandonedCpsRef = useRef(0);

  const stop = useCallback((opts) => {
    const keep = Boolean(opts && opts.keepSubtitle);
    stopSpeaking();
    stoppingRef.current = true;
    finishedRef.current = true;
    exitDocumentFullscreen(typeof document !== "undefined" ? document : null);
    restoreFollowView(typeof window !== "undefined" ? window.__naviguideScene : null, null);
    pinnedIdxRef.current = null;
    pinnedCharRef.current = null;
    filmBubbleRef.current.reset();
    filmScoreRef.current.reset();
    publishedBubbleRef.current = null;
    publishEventBubble(null);
    const cleared = applyReplayStop({
      cancelRaf: () => {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      },
      keepChapterText: keep,
      chapterText: keep ? chapterTextRef.current : "",
    });
    setActive(cleared.active);
    setTMs(cleared.tMs);
    setCard(cleared.card);
    setChapterIdx(cleared.chapterIdx);
    setChapterText(cleared.chapterText);
    chapterTextRef.current = cleared.chapterText || "";
    setSubtitle(cleared.chapterText || "");
    setSubtitlePlace("");
    lastSubtitleRef.current = cleared.chapterText || "";
    setFilmLeg(cleared.filmLeg);
    catchupRef.current = null;
    hiddenRef.current = false;
    setVoiceRate(1);
    setProgress(cleared.progress);
    queueRef.current = [];
    lastTRef.current = null;
    tMsRef.current = null;
    voiceTargetRef.current = null;
    recaleRemainRef.current = 0;
    lastBoundaryCharRef.current = 0;
    lastBoundaryAtRef.current = 0;
    voiceHoldRef.current = false;
    phraseEndedRef.current = false;
    skipRampRef.current = null;
    filmElapsedRef.current = 0;
    linearHoldRef.current = false;
    voiceAbandonedCpsRef.current = 0;
    planRef.current = null;
  }, []);

  const applyChapter = useCallback((ch) => {
    if (!ch) return;
    chapterIdxRef.current = ch.idx;
    voiceCharRef.current = 0;
    voiceBoundaryAtRef.current = 0;
    chapterStartedAtRef.current = typeof performance !== "undefined" ? performance.now() : 0;
    voiceTargetRef.current = Number.isFinite(ch.tA) ? ch.tA : null;
    recaleRemainRef.current = 0;
    lastBoundaryCharRef.current = 0;
    lastBoundaryAtRef.current = typeof performance !== "undefined" ? performance.now() : 0;
    voicePhraseOnRef.current = false;
    voicePhraseAtRef.current = 0;
    voicePhraseChar0Ref.current = 0;
    voiceHoldRef.current = false;
    phraseEndedRef.current = false;
    skipRampRef.current = null;
    if (Number.isFinite(ch.tA)) tMsRef.current = ch.tA;
    setChapterIdx(ch.idx);
    chapterTextRef.current = ch.text || "";
    setChapterText(ch.text || "");
    const first = filmBarSubtitle({
      chapterText: ch.text || "",
      charIdx: 0,
      pinned: pinnedIdxRef.current != null,
      sentenceStarts: ch.sentenceStarts,
      fromName: ch.fromName,
      toName: ch.toName,
      anchors: ch.anchors,
    });
    setSubtitle(first.text);
    setSubtitlePlace(first.place);
    lastSubtitleRef.current = first.text;
    setFilmLeg({
      fromLat: ch.fromLat, fromLon: ch.fromLon, toLat: ch.toLat, toLon: ch.toLon,
    });
  }, []);

  const finish = useCallback(() => {
    if (finishedRef.current || stoppingRef.current) return;
    if (!shouldReturnToLive({ filmFinished: true })) return;
    finishedRef.current = true;
    const w = windowRef.current;
    if (w) setTMs(w.endMs);
    setProgress(1);
    publishFilmEnd();
    setTimeout(() => stop({ keepSubtitle: true }), 400);
  }, [stop]);
  finishRef.current = finish;

  useEffect(() => {
    if (!enabled) return undefined;
    waitForVoices(typeof window !== "undefined" ? window : null, 1000);
    return undefined;
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setFilmStatus("pending");
      remotePlanRef.current = null;
      setEstimatedSeconds(0);
      setVariantEstimates(null);
      setFilmParagraphs([]);
      return undefined;
    }
    let cancelled = false;
    let retryTimer = 0;
    const ac = new AbortController();
    let requestTimer = 0;
    let requestTimedOut = false;
    const official = isOfficialFilmVoyage(voyageId);
    const path = filmRequestPath(voyageId);
    const style = filmRequestStyle(filmStyle);
    const q = `lang=${encodeURIComponent(lang)}&seconds=${encodeURIComponent(targetSeconds)}&style=${style}&t0=${encodeURIComponent(t0)}`;

    const applyEstimates = (data) => {
      const chapters = data?.chapters || [];
      const chars = Number(data?.chars) || chapters.reduce((n, c) => n + String(c?.text || "").length, 0);
      const est = Number(data?.estimatedSeconds) > 0
        ? Number(data.estimatedSeconds)
        : filmEstimatedSeconds(chars);
      setEstimatedSeconds(est);
      const estimates = data?.estimates && typeof data.estimates === "object" ? data.estimates : null;
      setVariantEstimates(estimates);
      setTargetSeconds((cur) => (filmVariantAbsent(cur, estimates) ? 0 : cur));
    };

    const applyStory = (data) => {
      const texts = (data?.chapters || []).map((c) => String(c?.text || "").trim()).filter(Boolean);
      setFilmParagraphs(texts);
    };

    const applyResolvedMeta = (data, requestedStyle) => {
      const resolved = resolveServedFilm(data, requestedStyle);
      if (resolved.updateHasWritten) setHasWritten(resolved.hasWritten);
      if (requestedStyle === "written" && filmStyle === "written" && !resolved.hasWritten) {
        setFilmStyle("raw");
      }
      return resolved;
    };

    const applyPlan = (data, resolved, requestedStyle = style) => {
      // Texte + anchors du stock (RG11A) : pas de réécriture navigateur.
      remotePlanRef.current = data;
      remotePlanKeyRef.current = q;
      setFilmLoadedStyle(resolved.effectiveStyle === requestedStyle ? requestedStyle : "mismatch");
      setFilmSource(resolved.source);
      setFilmReviewedBy(resolved.reviewedBy || "");
      setFilmModel(resolved.model || "");
      setFilmWebContext((prev) => nextFilmWebContext(prev, resolved));
      setFilmReceipt(resolved.receipt || null);
      applyEstimates(data);
      applyStory(data);
    };

    const applyData = (data, requestedStyle = style) => {
      if (cancelled) return true;
      if (isPreparingFilm(data)) {
        remotePlanRef.current = null;
        setFilmParagraphs([]);
        setFilmStatus("preparing");
        return "preparing";
      }
      const resolved = applyResolvedMeta(data, requestedStyle);
      const isProbe = requestedStyle === "written" && filmStyle !== "written";
      if (!isProbe && !filmBudgetCanPlay({
        chars: filmPayloadChars(data),
        budgetSeconds: targetSeconds,
      })) {
        applyEstimates(data);
        remotePlanRef.current = null;
        remotePlanKeyRef.current = "";
        setFilmParagraphs([]);
        setFilmStatus("pending");
        return "over-budget";
      }
      if (isReadyRemoteFilm(data, { official })) {
        if (!isProbe) applyPlan(data, resolved, requestedStyle);
        if (!isProbe) setFilmStatus("ready");
        return isProbe ? "probed" : true;
      }
      if (data?.chapters?.length) {
        if (!isProbe) {
          applyPlan(data, resolved, requestedStyle);
          setFilmStatus("stale");
        }
        return isProbe ? "probed" : true;
      }
      return false;
    };

    const markAbsent = () => {
      remotePlanRef.current = null;
      setHasWritten(false);
      setFilmSource("rules");
      setFilmReviewedBy("");
      setFilmModel("");
      setFilmWebContext(null);
      setFilmReceipt(null);
      setFilmWriting(false);
      setFilmLoadedStyle("");
      setEstimatedSeconds(0);
      setVariantEstimates(null);
      setFilmParagraphs([]);
      setFilmStatus("absent");
    };

    const probeWritten = () => {
      if (style !== "raw" || !official) return;
      const pq = `lang=${encodeURIComponent(lang)}&seconds=${encodeURIComponent(targetSeconds)}&style=written&t0=${encodeURIComponent(t0)}`;
      fetch(`${API}${path}?${pq}`, { signal: ac.signal })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (cancelled || ac.signal.aborted || !data) return;
          const resolved = applyResolvedMeta(data, "written");
          if (!resolved?.hasWritten || !resolved.source) return;
          setFilmSource(resolved.source);
          setFilmReviewedBy(resolved.reviewedBy || "");
          setFilmModel(resolved.model || "");
          setFilmWebContext((prev) => nextFilmWebContext(prev, resolved));
          setFilmReceipt(resolved.receipt || null);
        })
        .catch((err) => {
          if (err?.name === "AbortError" || cancelled || ac.signal.aborted) return;
        });
    };

    const load = () => {
      if (cancelled) return;
      const keepReady = remoteStatusRef.current === "ready" && remotePlanRef.current
        && filmQueryKeepsReady(remotePlanKeyRef.current, q);
      if (!keepReady) {
        setFilmStatus("pending");
        remotePlanRef.current = null;
      }
      fetch(`${API}${path}?${q}`, { signal: ac.signal })
        .then((r) => {
          if (!r.ok) return { fail: true, status: r.status };
          return r.json().then((data) => ({ data })).catch(() => ({ fail: true }));
        })
        .then((pack) => {
          clearTimeout(requestTimer);
          if (cancelled || ac.signal.aborted) return;
          if (!pack || pack.fail) {
            if (!filmResponseShouldRetry(pack?.status)) {
              markAbsent();
              return;
            }
            markAbsent();
            return;
          }
          const applied = applyData(pack.data);
          if (applied === "over-budget") return;
          if (applied === "preparing") {
            retryTimer = setTimeout(load, FILM_PREPARE_POLL_MS);
            return;
          }
          if (applied) {
            probeWritten();
            return;
          }
          setFilmStatus("empty");
          retryTimer = setTimeout(load, 2000);
        })
        .catch((err) => {
          clearTimeout(requestTimer);
          if (cancelled) return;
          if (requestTimedOut) {
            setFilmStatus("timeout");
            return;
          }
          if (err?.name === "AbortError" || ac.signal.aborted) return;
          markAbsent();
        });
      requestTimedOut = false;
      requestTimer = setTimeout(() => {
        requestTimedOut = true;
        ac.abort();
      }, 30_000);
    };

    load();
    return () => {
      cancelled = true;
      ac.abort();
      clearTimeout(retryTimer);
      clearTimeout(requestTimer);
    };
  }, [enabled, lang, targetSeconds, filmStyle, t0, voyageId, setFilmStatus, filmLoadAttempt]);

  const retryFilmLoad = useCallback(() => setFilmLoadAttempt((n) => n + 1), []);

  const canStart = canStartOfficialReplay({
    requireOfficialFilm,
    officialClock: clock,
    fallbackClock,
    remoteStatus,
  });

  const seekChapter = useCallback((idx, charIdx) => {
    const plan = planRef.current;
    if (!plan?.chapters?.length) return false;
    const last = plan.chapters.length - 1;
    const n = Math.max(0, Math.min(last, Number(idx)));
    const ch = plan.chapters[n];
    if (!ch) return false;
    const fromStart = Number(charIdx) === 0;
    applyChapter(ch);
    if (fromStart) {
      // Jouer la jambe depuis tA (Fort-de-France → Pointe-à-Pitre),
      // sans épingler tB — sinon le bateau reste à quai et la caméra ne glisse pas.
      pinnedIdxRef.current = null;
      pinnedCharRef.current = null;
      let chars = 0;
      for (let i = 0; i < n; i++) chars += Number(plan.chapters[i].chars) || 0;
      const elapsed = chars / FILM_ESTIMATE_CPS;
      filmElapsedRef.current = elapsed;
      displayElapsedRef.current = elapsed;
      const at = Number.isFinite(ch.tA) ? ch.tA : ch.tB;
      if (Number.isFinite(at)) {
        tMsRef.current = at;
        lastTRef.current = at;
        setTMs(at);
      }
    } else {
      pinnedIdxRef.current = ch.idx;
      const pinChar = Number.isFinite(Number(charIdx)) ? Math.max(0, Number(charIdx)) : null;
      pinnedCharRef.current = pinChar;
      if (pinChar != null) {
        const sub = filmBarSubtitle({
          chapterText: ch.text || "",
          charIdx: pinChar,
          pinned: true,
          sentenceStarts: ch.sentenceStarts,
          fromName: ch.fromName,
          toName: ch.toName,
          anchors: ch.anchors,
        });
        setSubtitle(sub.text);
        setSubtitlePlace(sub.place);
        lastSubtitleRef.current = sub.text;
      }
      const at = pinChar != null
        ? filmBoatTimeAtPhrase({
            chapter: ch, charIdx: pinChar, plan, chapterIdx: n, phraseEnded: false,
          })
        : (Number.isFinite(ch.tB) ? ch.tB : ch.tA);
      if (Number.isFinite(at)) {
        tMsRef.current = at;
        lastTRef.current = at;
        setTMs(at);
      }
    }
    if (ch.idx >= last) setProgress(1);
    if (typeof window !== "undefined") {
      const prev = window.__naviguideFilm || {};
      window.__naviguideFilm = {
        ...prev,
        chapterIdx: ch.idx,
        chapterText: ch.text || "",
        chapterCount: plan.chapters.length,
      };
    }
    return true;
  }, [applyChapter]);
  seekChapterRef.current = seekChapter;

  const start = useCallback(() => {
    stopSpeaking();
    const status = remoteStatusRef.current;
    const remote = remotePlanRef.current;
    const official = isOfficialFilmVoyage(voyageId);
    let clockToUse = clock;
    let remoteToUse = remote;
    if (requireOfficialFilm) {
      if (status === "ready" && isReadyRemoteFilm(remote, { official }) && clock) {
        clockToUse = clock;
        remoteToUse = remote;
      } else {
        return false;
      }
    }
    const w = replayWindow(clockToUse, Date.now());
    if (!w) return false;
    // Suivre : jamais le brut local (expeditionStory) servi comme film serveur.
    const local = requireOfficialFilm ? { chapters: [], source: "rules" } : buildFilmScript({
      clock: clockToUse,
      marks,
      live: destination,
      journal,
      lang,
      now: Date.now(),
      seconds: targetSeconds,
      t0,
    });
    const fallback = requireOfficialFilm ? [] : filmChaptersFromStory({
      clock: clockToUse,
      marks,
      live: destination,
      journal,
      lang,
      nowMs: Date.now(),
      t0,
    });
    const remoteOk = Boolean(
      remoteToUse?.chapters?.length
      && (
        isReadyRemoteFilm(remoteToUse, { official })
        || isRe7OfficialFilm(remoteToUse)
        || filmTextHasT0Year(remoteToUse.chapters, t0)
      ),
    );
    const picked = pickFilmChapters(
      remoteOk ? remoteToUse : null,
      requireOfficialFilm ? null : local,
      requireOfficialFilm ? [] : fallback,
    );
    const chapters = picked.chapters;
    setFilmSource(picked.source || local.source || "rules");
    setFilmReviewedBy("");
    setFilmModel("");
    setFilmWebContext(remoteOk ? publicFilmWebContext(remoteToUse) : null);
    setFilmReceipt(remoteOk ? publicFilmReceipt(remoteToUse) : null);
    const userBudget = Number(targetSeconds) > 0 ? Number(targetSeconds) : 0;
    const playedChars = chapters.reduce((n, c) => n + String(c?.text || "").length, 0);
    if (!filmBudgetCanPlay({ chars: playedChars, budgetSeconds: userBudget })) return false;
    budgetRef.current = userBudget;
    // Durée cochée ou non : un chapitre du texte reste un chapitre joué.
    // 2:30 fusionnait les chapitres courts (15 → 5) dès que le budget était 150.
    const planSeconds = resolveFilmTargetSeconds(userBudget, chapters);
    const plan = filmPlan({
      chapters,
      targetSeconds: planSeconds,
      keepChapters: true,
    });
    if (!plan.chapters.length) return false;
    clockRef.current = clockToUse;
    pinnedIdxRef.current = null;
    pinnedCharRef.current = null;
    windowRef.current = w;
    planRef.current = plan;
    queueRef.current = [];
    cardSinceRef.current = 0;
    lastTRef.current = plan.timeAt(0, 0);
    tMsRef.current = lastTRef.current;
    voiceTargetRef.current = lastTRef.current;
    recaleRemainRef.current = 0;
    lastBoundaryCharRef.current = 0;
    lastBoundaryAtRef.current = 0;
    voicePhraseOnRef.current = false;
    voicePhraseAtRef.current = 0;
    voicePhraseChar0Ref.current = 0;
    voiceHoldRef.current = false;
    phraseEndedRef.current = false;
    skipRampRef.current = null;
    filmElapsedRef.current = 0;
    linearHoldRef.current = false;
    voiceAbandonedCpsRef.current = 0;
    finishedRef.current = false;
    stoppingRef.current = false;
    startWallRef.current = 0;
    chapterStartedAtRef.current = 0;
    voiceCharRef.current = 0;
    voiceFailedRef.current = !voiceMayLead();
    voiceSpokenAllRef.current = false;
    voiceBoundaryAtRef.current = 0;
    catchupRef.current = null;
    hiddenRef.current = false;
    displayElapsedRef.current = 0;
    hiddenTRef.current = null;
    hiddenElapsedRef.current = 0;
    setVoiceRate(1);
    filmBubbleRef.current.reset();
    filmScoreRef.current.reset();
    publishedBubbleRef.current = null;
    publishEventBubble(null);
    setCard(null);
    applyChapter(plan.chapters[0]);
    setTMs(plan.timeAt(0, 0));
    setProgress(0);
    setActive(true);
    publishFilmStart(plan.targetSeconds);
    if (typeof window !== "undefined") {
      const prev = window.__naviguideFilm || {};
      window.__naviguideFilm = {
        ...prev,
        budgetSeconds: userBudget,
        chapterCount: plan.chapters.length,
        chapters: plan.chapters.map((c) => ({
          idx: c.idx,
          text: c.text || "",
          fromName: c.fromName || "",
          toName: c.toName || "",
          fromLat: c.fromLat,
          fromLon: c.fromLon,
          toLat: c.toLat,
          toLon: c.toLon,
          tA: c.tA,
          tB: c.tB,
        })),
        seekChapter: (idx, charIdx) => seekChapterRef.current?.(idx, charIdx),
        finishFilm: () => finishRef.current?.(),
      };
    }
    return true;
  }, [clock, requireOfficialFilm, marks, destination, journal, lang, targetSeconds, applyChapter, t0, voyageId]);

  useEffect(() => {
    if (!enabled && active) stop();
  }, [enabled, active, stop]);

  useEffect(() => {
    if (active) stop();
    // Berry ↔ ma route : on ne continue pas le film de l'autre source.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voyageId]);

  useEffect(() => {
    filmWritingRef.current = false;
    setFilmWriting(false);
    return () => {
      filmWriteGenerationRef.current += 1;
      filmWriteRequestRef.current?.abort();
      filmWriteRequestRef.current = null;
      filmWritingRef.current = false;
    };
  }, [voyageId]);

  const onVoiceBoundary = useCallback((charIdx) => {
    const plan = planRef.current;
    if (!plan || finishedRef.current) return;
    voiceCharRef.current = charIdx;
    voiceBoundaryAtRef.current = performance.now();
    lastBoundaryCharRef.current = charIdx;
    lastBoundaryAtRef.current = voiceBoundaryAtRef.current;
    const next = plan.timeAt(chapterIdxRef.current, charIdx);
    if (next == null) return;
    voiceTargetRef.current = next;
    recaleRemainRef.current = FILM_RECALE_MS;
  }, []);

  const onSentenceStart = useCallback((startChar) => {
    phraseEndedRef.current = false;
    voiceHoldRef.current = false;
    const at = Math.max(0, Number(startChar) || 0);
    voiceCharRef.current = at;
    lastBoundaryCharRef.current = at;
    lastBoundaryAtRef.current = typeof performance !== "undefined" ? performance.now() : 0;
    voicePhraseOnRef.current = true;
    voicePhraseAtRef.current = lastBoundaryAtRef.current;
    voicePhraseChar0Ref.current = at;
    recaleRemainRef.current = 0;
  }, []);

  const onSentenceEnd = useCallback((endChar) => {
    phraseEndedRef.current = true;
    const plan = planRef.current;
    const ch = plan?.chapters?.[chapterIdxRef.current];
    if (!plan || !ch) return;
    const sent = sentenceSpan(ch, Math.max(0, (Number(endChar) || 1) - 1));
    const cur = tMsRef.current ?? sent.endT;
    const atQuay = Boolean(clockRef.current)
      && sentenceIsStationary(clockRef.current, sent.startT, sent.endT);
    const cap = filmTimeWhileChapterSpeaks({
      t: sent.endT, chapter: ch, hold: true, clock: clockRef.current,
    });
    const arrived = Number.isFinite(cur) && (
      cur + 80 >= sent.endT || (Number.isFinite(cap) && cur + 1 >= cap)
    );
    const wait = voiceShouldWait({
      t: arrived ? sent.endT : cur, sentenceEndT: sent.endT, phraseEnded: true, atQuay,
    });
    voiceHoldRef.current = Boolean(wait.wait);
    if (wait.skip && clockRef.current) {
      const toT = nextMovingTime(clockRef.current, ch, Math.max(cur, sent.endT));
      if (Number.isFinite(toT) && toT > cur + 50) {
        skipRampRef.current = {
          fromT: cur, toT, startedAt: performance.now(), durationMs: 1000,
        };
        voiceHoldRef.current = true;
      }
    }
  }, []);

  const isVoiceHeld = useCallback(() => voiceHoldRef.current, []);

  const abandonVoiceNow = useCallback(() => {
    if (stoppingRef.current || finishedRef.current || voiceFailedRef.current) return;
    stopSpeaking();
    const abandoned = abandonVoiceToLinear({
      plan: planRef.current,
      chapterIdx: chapterIdxRef.current,
      charIdx: voiceCharRef.current,
    });
    filmElapsedRef.current = abandoned.elapsed;
    voiceAbandonedCpsRef.current = abandoned.cps;
    voiceFailedRef.current = true;
    voiceHoldRef.current = false;
    linearHoldRef.current = false;
  }, []);

  const onVoiceLeadFailed = useCallback(() => {
    abandonVoiceNow();
  }, [abandonVoiceNow]);

  const onVoiceEnd = useCallback(() => {
    const plan = planRef.current;
    if (!plan || finishedRef.current || stoppingRef.current) return;
    if (!voiceRef.current || voiceFailedRef.current || !canLeadWithVoice()) return;
    // E2 : onend sans mot dit → horloge murale, jamais finish() au chapitre 0.
    if (!(voiceBoundaryAtRef.current > 0 && voiceCharRef.current > 0)) {
      abandonVoiceNow();
      return;
    }
    const idx = chapterIdxRef.current;
    // Pas de bond à tB — le gouverneur a déjà rejoint l'ancre, ou la rampe d'escale.
    const wallElapsed = startWallRef.current
      ? (performance.now() - startWallRef.current) / 1000
      : 0;
    // Débit constant (27 sept.) : on ne recalibre plus la voix pour tenir le budget — c'était
    // l'accélération audible après le premier chapitre. Le budget (2:30 / 3:00) choisit le TEXTE
    // côté serveur ; la durée réelle suit la voix, et le bateau suit la voix.
    if (idx + 1 >= plan.chapters.length) {
      if (shouldHoldFilmForBudget({
        userBudget: budgetRef.current,
        wallElapsed,
        lastChapter: true,
      })) {
        // Voix finie avant le budget : on tient la dernière image ; la boucle finira au budget.
        voiceSpokenAllRef.current = true;
        return;
      }
      finish();
      return;
    }
    chapterStartedAtRef.current = performance.now();
    applyChapter(plan.chapters[idx + 1]);
  }, [applyChapter, finish, abandonVoiceNow]);

  // The loop: wall clock → expedition time; journal lines passed → cards, one at a time.
  useEffect(() => {
    if (!active) return undefined;
    let prev = performance.now();
    const tick = (now) => {
      const dt = Math.min(200, now - prev);
      prev = now;
      if (startWallRef.current === 0) {
        startWallRef.current = now;
        chapterStartedAtRef.current = now;
      }
      const plan = planRef.current;
      const w = windowRef.current;
      if (!plan || !w || finishedRef.current) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      const wallElapsed = (now - startWallRef.current) / 1000;
      const catchup = catchupRef.current;
      let elapsed = wallElapsed;
      if (catchup) {
        const u = Math.max(0, Math.min(1, (now - catchup.startedAt) / Math.max(1, catchup.durationMs)));
        const ease = 1 - (1 - u) * (1 - u);
        elapsed = catchup.fromElapsed + (catchup.toElapsed - catchup.fromElapsed) * ease;
      } else if (!linearHoldRef.current) {
        filmElapsedRef.current += dt / 1000;
      }
      if (!catchup) elapsed = filmElapsedRef.current;
      displayElapsedRef.current = elapsed;
      const linearCps = voiceAbandonedCpsRef.current || FILM_ESTIMATE_CPS;
      const speakDenom = Math.max(wallClockSpeakSeconds(plan, linearCps), Number(plan.targetSeconds) || 0, 1);
      const uiDue = now - lastUiAtRef.current >= FILM_UI_MS;
      if (!voiceMayLead()) {
        voiceFailedRef.current = true;
      }
      const chapterAge = chapterStartedAtRef.current ? now - chapterStartedAtRef.current : 0;
      // Playwright / voix absente : speechSynthesis.speaking peut rester
      // collé sans onEnd — ça ne doit pas geler applyChapter ni chapterIdx.
      const engineSpeaking = Boolean(voiceRef.current) && isSpeaking() && canLeadWithVoice();
      // Une synthèse coincée (speaking vrai, plus de mots) n'est plus
      // une voix vivante — le film ignore le flag Chrome après abandon.
      const speaking = engineSpeaking && !voiceFailedRef.current;
      if (
        voiceRef.current && !voiceFailedRef.current && !voiceSpokenAllRef.current
        && voiceStalled({
          chapterAgeMs: chapterAge,
          sinceBoundaryMs: voiceBoundaryAtRef.current === 0
            ? Infinity
            : now - voiceBoundaryAtRef.current,
          speaking: engineSpeaking,
          hold: voiceHoldRef.current,
        })
      ) {
        abandonVoiceNow();
      }
      const voiceClock = Boolean(
        voiceRef.current
        && !voiceFailedRef.current
        && voiceMayLead(),
      );
      const voiceLed = Boolean(voiceClock && voiceCharRef.current > 0);
      if (uiDue) {
        lastUiAtRef.current = now;
        setProgress(voiceClock
          ? spokenProgress(plan, chapterIdxRef.current, voiceCharRef.current)
          : Math.max(0, Math.min(1, elapsed / speakDenom)));
      }

      const ingest = (next) => {
        if (next == null) return;
        const from = lastTRef.current ?? next;
        const fresh = cardsBetween(timelineRef.current, from, next, lang, clockRef.current);
        if (fresh.length) queueRef.current = trimQueue([...queueRef.current, ...fresh]);
        lastTRef.current = next;
        tMsRef.current = next;
        if (uiDue) setTMs(next);
      };
      const ingestHeld = (raw, chapter, { hold = true } = {}) => {
        if (!hold) {
          ingest(filmTimeWhileChapterSpeaks({
            t: raw, chapter, hold: false, clock: clockRef.current,
          }));
          return false;
        }
        const capped = filmChapterPlayheadCapped({
          t: raw, chapter, clock: clockRef.current,
        });
        ingest(capped.t);
        return capped.atCap;
      };

      let charIdx = voiceCharRef.current;
      const linear = linearFilmAt(elapsed, plan, linearCps);
      // E2 : fini seulement à la dernière phrase (horloge 15 car./s), jamais au budget
      // au milieu du récit ni sur un onend sans mot. Voix vraiment finie : on tient le budget.
      const voiceAllDone = Boolean(voiceSpokenAllRef.current) && (
        budgetRef.current <= 0 || wallElapsed >= plan.targetSeconds
      );
      // La clôture se finit — tant que la voix parle, pas de finish().
      const done = filmShouldFinish({
        voiceClock,
        speaking,
        voiceAllDone,
        linearFinish: linear.finish,
        lastReached: linear.lastReached,
        stopping: stoppingRef.current,
      });
      if (done) {
        const last = plan.chapters[plan.chapters.length - 1];
        ingest(last?.tB ?? w.endMs);
        // Fin du film : le sous-titre reste sur la dernière phrase (sans voix,
        // voiceCharRef vaut 0 et ramenait la 1re phrase du dernier chapitre).
        charIdx = filmEndCharIdx(last, chapterIdxRef.current, plan.chapters.length, charIdx);
        finish();
      } else if (catchup) {
        const spokenCh = plan.chapters[chapterIdxRef.current];
        const liveTarget = (voiceClock || speaking)
          ? filmTimeWhileChapterSpeaks({
            t: plan.timeAt(chapterIdxRef.current, voiceCharRef.current),
            chapter: spokenCh,
            hold: true,
            clock: clockRef.current,
          })
          : plan.timeAt(linear.chapterIdx, linear.charIdx);
        if (liveTarget != null) catchup.toT = liveTarget;
        const stepped = visibilityCatchupStep({
          fromT: catchup.fromT,
          toT: catchup.toT,
          elapsedMs: now - catchup.startedAt,
          durationMs: catchup.durationMs,
        });
        if (shouldApplyChapterFromClock({ voiceClock, speaking })) {
          const ch = pinnedIdxRef.current != null
            ? plan.chapters[pinnedIdxRef.current]
            : plan.chapters[linear.chapterIdx];
          if (ch && ch.idx !== chapterIdxRef.current) applyChapter(ch);
          charIdx = pinnedIdxRef.current != null ? (ch?.chars || 1) : linear.charIdx;
        } else {
          charIdx = voiceCharRef.current;
        }
        const atCap = ingestHeld(stepped.t, plan.chapters[chapterIdxRef.current]);
        if (atCap) {
          linearHoldRef.current = false;
          voiceHoldRef.current = false;
        }
        if (stepped.done) {
          catchupRef.current = null;
          filmElapsedRef.current = wallElapsed;
        }
      } else if (!voiceClock) {
        const pinned = pinnedIdxRef.current;
        const linearCh = pinned != null ? plan.chapters[pinned] : plan.chapters[linear.chapterIdx];
        // ApplyChapter seulement à onEnd si la voix mène ou parle encore
        // (isSpeaking est faux entre deux phrases — ne pas basculer là).
        if (
          linearCh
          && linearCh.idx !== chapterIdxRef.current
          && shouldApplyChapterFromClock({ voiceClock, speaking })
        ) {
          applyChapter(linearCh);
        }
        const ch = plan.chapters[chapterIdxRef.current];
        if (pinned != null && ch) {
          charIdx = pinnedCharRef.current != null ? pinnedCharRef.current : (ch.chars || 1);
          const pinT = pinnedCharRef.current != null
            ? filmBoatTimeAtPhrase({
                chapter: ch,
                charIdx: pinnedCharRef.current,
                plan,
                chapterIdx: ch.idx ?? pinned,
                phraseEnded: false,
              })
            : (Number.isFinite(ch.tB) ? ch.tB : plan.timeAt(0, 0));
          ingestHeld(Number.isFinite(pinT) ? pinT : ch.tA, ch, { hold: false });
        } else {
          if (ch && linear.chapterIdx > ch.idx) {
            // RC52 : elapsed a fini le chapitre, la phrase pas — pas tB.
            const keep = Math.max(0, Number(voiceCharRef.current) || 0);
            const sentHold = sentenceSpan(ch, keep);
            const atLast = keep + 1e-6 >= (ch.chars || 1) - 1e-6
              || (phraseEndedRef.current && sentHold.end + 1e-6 >= (ch.chars || 1));
            charIdx = atLast ? (ch.chars || 1) : keep;
          } else {
            charIdx = linear.charIdx;
          }
          const sent = sentenceSpan(ch, charIdx);
          const phraseEnded = Boolean(ch) && charIdx + 1e-6 >= sent.end;
          const cur = tMsRef.current ?? lastTRef.current ?? ch?.tA;
          const mapZoom = typeof window !== "undefined"
            ? Number(window.__naviguideScene?.map?.getZoom?.())
            : NaN;
          const stepped = stepFilmTime({
            t: cur,
            dt: dt / 1000,
            chapter: ch,
            plan,
            chapterIdx: ch?.idx ?? 0,
            charIdx,
            clock: clockRef.current,
            zoom: Number.isFinite(mapZoom) ? mapZoom : chapterZoomEstimate(ch),
            lat: ch?.fromLat,
            voiceLed: false,
            phraseEnded,
            skipRamp: skipRampRef.current,
            nowMs: now,
          });
          skipRampRef.current = stepped.skipRamp;
          const atCap = ingestHeld(stepped.t, ch);
          // En linéaire, geler filmElapsed à une frontière de phrase
          // bloque charIdx → plus jamais de chapitre suivant.
          linearHoldRef.current = Boolean(voiceClock && stepped.voiceHold && !atCap);
          voiceHoldRef.current = Boolean(stepped.voiceHold) && !atCap;
        }
      } else {
        const ch = plan.chapters[chapterIdxRef.current];
        const cur = tMsRef.current ?? lastTRef.current ?? ch?.tA;
        const mapZoom = typeof window !== "undefined"
          ? Number(window.__naviguideScene?.map?.getZoom?.())
          : NaN;
        const since = lastBoundaryAtRef.current
          ? (now - lastBoundaryAtRef.current) / 1000
          : 0;
        const stepped = stepFilmTime({
          t: cur,
          dt: dt / 1000,
          chapter: ch,
          plan,
          chapterIdx: chapterIdxRef.current,
          charIdx: voiceCharRef.current,
          cps: measuredCps(voiceCharRef.current, chapterStartedAtRef.current ? now - chapterStartedAtRef.current : 0),
          lastBoundaryChar: lastBoundaryCharRef.current,
          sinceBoundaryS: since,
          recaleRemainMs: recaleRemainRef.current,
          clock: clockRef.current,
          zoom: Number.isFinite(mapZoom) ? mapZoom : chapterZoomEstimate(ch),
          lat: ch?.fromLat,
          voiceLed: true,
          phraseEnded: phraseEndedRef.current,
          skipRamp: skipRampRef.current,
          nowMs: now,
        });
        recaleRemainRef.current = stepped.recaleRemainMs;
        skipRampRef.current = stepped.skipRamp;
        const atCap = ingestHeld(stepped.t, ch);
        voiceHoldRef.current = Boolean(stepped.voiceHold) && !atCap;
      }

      const chapter = plan.chapters[chapterIdxRef.current];
      if (voiceClock && pinnedIdxRef.current == null) {
        const sent = sentenceSpan(chapter, voicePhraseChar0Ref.current);
        const phraseElapsedS = voicePhraseAtRef.current
          ? (now - voicePhraseAtRef.current) / 1000
          : 0;
        charIdx = filmScriptCharIdx({
          voiceClock: true,
          phraseOn: voicePhraseOnRef.current,
          phraseEnded: phraseEndedRef.current,
          phraseChar0: voicePhraseChar0Ref.current,
          phraseElapsedS,
          sentenceEndChar: sent?.end,
          chapterChars: chapter?.chars,
          linearChar: linear.charIdx,
        });
      }
      // RC52 : le bateau publié suit charIdx, pas elapsed / tB.
      const sentPub = chapter ? sentenceSpan(chapter, charIdx) : null;
      const phraseDone = Boolean(
        phraseEndedRef.current
        || (sentPub && charIdx + 1e-6 >= sentPub.end),
      );
      const boatT = filmBoatTimeAtPhrase({
        chapter,
        charIdx,
        plan,
        chapterIdx: chapterIdxRef.current,
        phraseEnded: phraseDone,
        t: lastTRef.current,
      });
      const curBoat = lastTRef.current;
      const tBpub = chapterTimeMs(chapter?.tB);
      const pastPhrase = sentPub && Number.isFinite(sentPub.endT)
        && Number.isFinite(curBoat) && curBoat > sentPub.endT + 1;
      const atChapterEnd = Number.isFinite(tBpub) && Number.isFinite(curBoat)
        && curBoat + 2 >= tBpub;
      if (!phraseDone && Number.isFinite(boatT) && (pastPhrase || atChapterEnd)) {
        ingestHeld(boatT, chapter);
      }
      const sub = filmBarSubtitle({
        chapterText: chapter?.text || "",
        charIdx,
        pinned: pinnedIdxRef.current != null,
        sentenceStarts: chapter?.sentenceStarts,
        fromName: chapter?.fromName,
        toName: chapter?.toName,
        anchors: chapter?.anchors,
      });
      // Tick de fin : le sous-titre de clôture part au DOM même hors cadence UI.
      if ((uiDue || done) && sub.text !== lastSubtitleRef.current) {
        lastSubtitleRef.current = sub.text;
        setSubtitle(sub.text);
        setSubtitlePlace(sub.place);
      } else if (uiDue) {
        setSubtitlePlace(sub.place);
      }
      const span = chapter && Number.isFinite(chapter.tB - chapter.tA) ? (chapter.tB - chapter.tA) : 0;
      const approachFrac = span > 0
        ? Math.max(0, Math.min(1, (lastTRef.current - chapter.tA) / span))
        : (charIdx / (chapter?.chars || 1));
      if (typeof window !== "undefined" && publishedBubbleRef.current && !window.__naviguideEventBubble) {
        filmBubbleRef.current.dismiss();
        publishedBubbleRef.current = null;
        setCard(null);
      }
      const filmEv = pickFilmEvent({
        chapter,
        charIdx,
        tMs: lastTRef.current,
        voiceLed,
        plan,
      }) || approachStopEvent(chapter, { frac: approachFrac });
      const destName = chapter?.toName || "";
      const fittingEv = filmEv && arrivalBubbleFitsDestination(filmEventCard(filmEv, lang), destName)
        ? filmEv
        : null;
      const accepted = filmScoreRef.current.accept(fittingEv);
      let shown = filmBubbleRef.current.propose(filmEventCard(accepted, lang));
      if (shown && !arrivalBubbleFitsDestination(shown, destName)) {
        filmBubbleRef.current.dismiss();
        shown = null;
      }
      if (shown !== publishedBubbleRef.current) {
        publishedBubbleRef.current = shown;
        if (shown) {
          cardSinceRef.current = now;
          setCard(shown);
        } else {
          setCard(null);
        }
        publishEventBubble(shown);
      }
      if (typeof window !== "undefined") {
        const pos = positionAt(clockRef.current, lastTRef.current);
        const sample = replaySample(clockRef.current, lastTRef.current, timelineRef.current);
        const prevFilm = window.__naviguideFilm || {};
        window.__naviguideFilm = {
          ...prevFilm,
          chapterIdx: chapterIdxRef.current,
          chapterText: chapter?.text || prevFilm.chapterText || "",
          fromName: chapter?.fromName || "",
          toName: chapter?.toName || "",
          subtitle: sub.text,
          subtitlePlace: sub.place,
          chapterCount: plan.chapters.length,
          elapsed,
          charIdx,
          tMs: lastTRef.current,
          lat: pos?.lat ?? sample?.lat ?? null,
          lon: pos?.lon ?? sample?.lon ?? null,
          heading: sample?.bearing ?? prevFilm.heading ?? null,
          filmNm: pos?.filmNm ?? sample?.filmNm ?? null,
          bubbleId: shown ? (shown.key || shown.id || null) : null,
          bubbleKind: shown?.kind || null,
          seekChapter: prevFilm.seekChapter || ((idx, charIdx) => seekChapterRef.current?.(idx, charIdx)),
          finishFilm: prevFilm.finishFilm || (() => finishRef.current?.()),
        };
      }

      // Card rotation: journal lines fill the sidebar only when no chapter
      // event is on screen — the bubble and the NOW card stay the same text.
      if (!shown && queueRef.current.length && now - cardSinceRef.current >= cardDwellMs(queueRef.current.length)) {
        const nextCard = queueRef.current.shift();
        cardSinceRef.current = now;
        setCard(nextCard);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
  }, [active, secondsPerDay, lang, stop, finish, applyChapter, abandonVoiceNow]);

  useEffect(() => {
    if (!active || typeof document === "undefined") return undefined;
    const onVis = () => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      const plan = planRef.current;
      if (document.hidden) {
        hiddenRef.current = true;
        hiddenTRef.current = tMsRef.current;
        hiddenElapsedRef.current = displayElapsedRef.current;
        return;
      }
      if (!hiddenRef.current) return;
      hiddenRef.current = false;
      const wallElapsed = startWallRef.current ? (now - startWallRef.current) / 1000 : 0;
      const fromT = hiddenTRef.current ?? tMsRef.current;
      const fromElapsed = hiddenElapsedRef.current ?? displayElapsedRef.current ?? wallElapsed;
      let toT = tMsRef.current;
      if (plan) {
        const voiceClock = Boolean(
          voiceRef.current && !voiceFailedRef.current && voiceMayLead(),
        );
        if (voiceClock && voiceCharRef.current > 0) {
          const next = plan.timeAt(chapterIdxRef.current, voiceCharRef.current);
          if (next != null) toT = next;
        } else {
          const linear = linearFilmAt(
            wallElapsed,
            plan,
            voiceAbandonedCpsRef.current || FILM_ESTIMATE_CPS,
          );
          const next = plan.timeAt(linear.chapterIdx, linear.charIdx);
          if (next != null) toT = next;
        }
      }
      catchupRef.current = {
        fromT,
        toT,
        fromElapsed,
        toElapsed: wallElapsed,
        startedAt: now,
        durationMs: FILM_VISIBILITY_CATCHUP_MS,
      };
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [active]);

  const live = useMemo(() => (active && tMs != null ? replaySample(clock, tMs, timeline) : null), [active, tMs, clock, timeline]);
  const clockProgress = active && tMs != null ? replayProgress(tMs, windowRef.current) : 0;

  const dismissCard = useCallback(() => {
    filmBubbleRef.current.dismiss();
    publishedBubbleRef.current = null;
    publishEventBubble(null);
    setCard(null);
    cardSinceRef.current = 0;
  }, []);

  const chooseFilmStyle = useCallback((next) => {
    if (next !== "written") {
      // Switching back to Raw must stop an in-flight write poll even when
      // filmStyle is already "raw" and the style effect cannot observe a change.
      filmWriteGenerationRef.current += 1;
      filmWriteRequestRef.current?.abort();
      filmWriteRequestRef.current = null;
      filmWritingRef.current = false;
      filmWritePollGenRef.current += 1;
      filmWritePollAbortRef.current?.abort();
      filmWritePollAbortRef.current = null;
      filmWriteStartingRef.current = false;
      setFilmWriting(false);
      setFilmStyle("raw");
      return;
    }
    // Les films personnalisés n'ont pas de variante Rédigé.
    if (!isOfficialFilmVoyage(voyageId)) {
      setFilmStyle("raw");
      return;
    }
    if (hasWritten) {
      setFilmWriting(false);
      setFilmStyle("written");
      return;
    }
    if (filmWritingRef.current) return;
    if (filmWriteStartingRef.current) return; // double-click guard
    if (active && !hasWritten) return;
    if (active) stop();
    if (!isOfficialFilmVoyage(voyageId)) return;
    const path = filmRequestPath(voyageId);
    const q = `lang=${encodeURIComponent(lang)}&seconds=${encodeURIComponent(targetSeconds)}&t0=${encodeURIComponent(t0)}`;
    setFilmWriteError(false);
    setWrittenUnavailable(null);
    filmWritingRef.current = true;
    const generation = ++filmWriteGenerationRef.current;
    const controller = new AbortController();
    filmWriteRequestRef.current = controller;
    const timeout = setTimeout(() => controller.abort(), 30_000);
    const writeGen = ++filmWritePollGenRef.current;
    filmWriteStartingRef.current = true;
    setFilmWriting(true);
    fetch(`${API}${path}?${q}`, { method: "POST", signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`film write HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (generation !== filmWriteGenerationRef.current) return;
        if (writeGen !== filmWritePollGenRef.current) return;
        if (!data) {
          // RL191: a network miss is not "unavailable"; only a cascade failure is.
          setWrittenUnavailable(null);
          setFilmWriteError(true);
          setFilmWriting(false);
          return;
        }
        if (data?.reason === "all-providers-failed") setWrittenUnavailable("unavailable");
        const status = String(data?.status || "").toLowerCase();
        if (status === "writing" || data?.writing) {
          void filmWriteNextStepRef.current();
          return;
        }
        const resolved = resolveServedFilm(data, "written");
        if (resolved.hasWritten) {
          setHasWritten(true);
          setFilmStyle("written");
          setFilmSource(resolved.source);
          setFilmReviewedBy(resolved.reviewedBy || "");
          setFilmModel(resolved.model || "");
          setFilmWebContext((prev) => nextFilmWebContext(prev, resolved));
          setFilmReceipt(resolved.receipt || null);
          setWrittenUnavailable(null);
          setFilmWriting(false);
          return;
        }
        // A successful HTTP response can still mean that writing did not
        // start (LLM disabled, budget exhausted, or no valid raw plan).
        // RL191: "unavailable" only once the whole cascade failed.
        setFilmWriteError(true);
        setWrittenUnavailable(data?.reason === "all-providers-failed" ? "unavailable" : null);
        setFilmWriting(false);
      })
      .catch(() => {
        if (writeGen !== filmWritePollGenRef.current) return;
        setFilmWriteError(true);
        setFilmWriting(false);
        // RL191: a network miss is not "unavailable"; only a cascade failure is.
        if (generation === filmWriteGenerationRef.current) setWrittenUnavailable(null);
      })
      .finally(() => {
        clearTimeout(timeout);
        if (generation === filmWriteGenerationRef.current) {
          filmWriteRequestRef.current = null;
          filmWritingRef.current = false;
        }
        if (writeGen === filmWritePollGenRef.current) {
          filmWriteStartingRef.current = false;
        }
      });
  }, [active, hasWritten, lang, stop, targetSeconds, t0, voyageId]);

  // filmWriteNextStep: polls GET /voyage/official/film?style=written every 4s, up to 10min
  const filmWriteNextStep = useCallback(async () => {
    if (!isOfficialFilmVoyage(voyageId)) return "stop";

    const gen = ++filmWritePollGenRef.current;
    filmWritePollAbortRef.current?.abort();
    const ac = new AbortController();
    filmWritePollAbortRef.current = ac;
    const path = filmRequestPath(voyageId);
    const q = `lang=${encodeURIComponent(lang)}&seconds=${encodeURIComponent(targetSeconds)}&style=written&t0=${encodeURIComponent(t0)}`;
    const maxAttempts = 150; // 4s * 150 = 600s = 10min
    let attempts = 0;

    const sleep = (ms) => new Promise((resolve, reject) => {
      const id = setTimeout(resolve, ms);
      ac.signal.addEventListener(
        "abort",
        () => {
          clearTimeout(id);
          reject(new DOMException("aborted", "AbortError"));
        },
        { once: true },
      );
    });

    try {
      while (attempts < maxAttempts) {
      if (gen !== filmWritePollGenRef.current) return "stop";
      try {
        await sleep(4000);
      } catch (err) {
        if (err?.name === "AbortError") return "stop";
        throw err;
      }
      attempts++;
      if (gen !== filmWritePollGenRef.current) return "stop";

      try {
        const res = await fetch(`${API}${path}?${q}`, { signal: ac.signal });
        if (!res.ok) continue;
        const data = await res.json();
        if (!data) continue;

        const status = data?.status?.toLowerCase();
        if (status === "preparing") continue;
        if (status === "failed") {
          setFilmWriteError(true);
          setWrittenUnavailable("unavailable");
          setFilmWriting(false);
          return "stop";
        }

        const resolved = resolveServedFilm(data, "written");
        if (resolved.hasWritten) {
          setHasWritten(true);
          setFilmStyle("written");
          setFilmSource(resolved.source);
          setFilmReviewedBy(resolved.reviewedBy || "");
          setFilmModel(resolved.model || "");
          setFilmWebContext(resolved.webContext || null);
          setFilmReceipt(resolved.receipt || null);
          setFilmWriteError(false);
          setWrittenUnavailable(null);
          setFilmWriting(false);
          return "ready";
        }
        if (resolved.effectiveStyle === "raw" && data.hasWritten === false) {
          // still writing
          continue;
        }
      } catch (err) {
        if (err?.name === "AbortError") return "stop";
        // ignore network errors, keep polling
      }
    }
      if (gen !== filmWritePollGenRef.current) return "stop";
      setFilmWriteError(true);
      setWrittenUnavailable("unavailable");
      setFilmWriting(false);
      return "stop";
    } finally {
      if (gen === filmWritePollGenRef.current) {
        filmWriteStartingRef.current = false;
      }
    }
  }, [lang, targetSeconds, t0, voyageId]);

  filmWriteNextStepRef.current = filmWriteNextStep;

  useEffect(() => {
    filmWritePollGenRef.current += 1;
    filmWritePollAbortRef.current?.abort();
    return () => {
      filmWritePollGenRef.current += 1;
      filmWritePollAbortRef.current?.abort();
      filmWritePollAbortRef.current = null;
      filmWriteStartingRef.current = false;
    };
  }, [voyageId, lang, targetSeconds, t0, filmStyle]);

  return {
    active,
    tMs,
    live,
    card,
    progress: active ? progress || clockProgress : 0,
    voice,
    setVoice,
    start,
    stop,
    dismissCard,
    timeline,
    targetSeconds,
    setTargetSeconds,
    chapterIdx,
    chapterText,
    fromName: (
      planRef.current?.chapters?.find((c) => c.idx === chapterIdx)
      || planRef.current?.chapters?.[chapterIdx]
      || {}
    ).fromName || "",
    toName: (
      planRef.current?.chapters?.find((c) => c.idx === chapterIdx)
      || planRef.current?.chapters?.[chapterIdx]
      || {}
    ).toName || "",
    subtitle,
    subtitlePlace,
    filmLeg,
    voiceRate,
    onVoiceBoundary,
    onVoiceEnd,
    onVoiceLeadFailed,
    onSentenceStart,
    onSentenceEnd,
    isVoiceHeld,
    filmSource,
    chapterProvenance: planRef.current?.chapters?.[chapterIdx]
      ? {
          model: planRef.current.chapters[chapterIdx].served_model || "",
          source: planRef.current.chapters[chapterIdx].served_source || "",
          tier: planRef.current.chapters[chapterIdx].served_tier || "",
        }
      : null,
    filmReviewedBy,
    filmModel,
    filmWebContext,
    filmReceipt,
    filmWriting,
    filmWriteError,
    filmStyle,
    setFilmStyle: chooseFilmStyle,
    filmWriteNextStep,
    hasWritten,
    writtenUnavailable,
    filmLoadedStyle,
    canStart,
    seekChapter,
    remoteStatus,
    retryFilmLoad,
    estimatedSeconds,
    variantEstimates,
    filmParagraphs,
    voyageId,
  };
}
