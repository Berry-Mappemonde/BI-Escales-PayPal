import { KIND_ICON } from "../engine/journalFormat.js";
import { localizeStoredTitle } from "./iciMaintenant.js";

export const EVENT_BUBBLE_MIN_MS = 3000;
export const EVENT_BUBBLE_FADE_MS = 200;
export const EVENT_BUBBLE_WIDTH = 280;
export const EVENT_BUBBLE_TITLE_MAX = 40;
export const BUBBLE_SCORE_SHOW = 2;
export const BUBBLE_SCORE_SUM = 3;
export const BUBBLE_SCORE_WINDOW_MS = 20_000;

export function createEventPopupOptions() {
  return {
    autoPan: false,
    closeButton: false,
    className: "event-bubble",
    maxWidth: EVENT_BUBBLE_WIDTH,
    minWidth: EVENT_BUBBLE_WIDTH,
    closeOnClick: false,
    autoClose: false,
    keepInView: false,
  };
}

export function ensureEventPopup(popup, L) {
  return popup || L.popup(createEventPopupOptions());
}

export function bubbleId(card) {
  if (!card) return null;
  return card.key || card.id || card.stableKey || `${card.kind || "?"}:${card.at || card.title || ""}`;
}

export function isNowAlertOrDecision(card) {
  if (!card) return false;
  if (card.severity === "alert") return true;
  if (card.lane === "now") return true;
  return card.judge === "now";
}

function isEnLang(lang) {
  return String(lang || "").toLowerCase().startsWith("en");
}

/** Titres de données gardés tels quels en EN (noms propres : escale, projet, campagne). */
const EN_KEEP_TITLE_KINDS = new Set(["stop", "project", "sci", "port", "poe", "news", "chat"]);

const EN_KIND_TITLE = Object.freeze({
  zee: "Maritime zone",
  amp: "Marine protected area",
  wx: "Sea conditions",
  climo: "Seasonal winds",
  coast: "Along the coast",
  geo: "Seabed",
  position: "Position",
  grib: "Weather",
  note: "Logbook",
});

const FR_WORD_RE = /(?:^|[\s,(])(?:du|des|les|une|entre|est|sont|aux|avec|dans|sur|pour|par|vers|et|limite|désaccord|navires?|flotte|aménagement|économique)(?=[\s,.;:)]|$)/gi;
const EN_WORD_RE = /(?:^|[\s,(])(?:the|of|on|and|at|in|boat|miles?|away|waters|near|from|to|between|arrival|project)(?=[\s,.;:)]|$)/gi;
const FR_STRONG_RE = /^(?:du|des|le|la|les|l['’]|au|aux|une?|zone économique|haute mer|aire marine)\s/i;
const FR_TITLE_RE = /^(?:l['’]|les?\s|la\s|du\s|des\s|aux?\s)|\b(?:alizés?|limite|plateau|zone|aire|haute mer|vents?|côte)\b/i;

/**
 * Un texte de données français ne doit pas apparaître dans l'interface EN.
 * Début français (« Du 11 Jun, … », « les Baléares ») ou plus de mots outils
 * français qu'anglais. Les noms propres (accents, « Côte À Côte ») ne comptent pas.
 */
export function looksFrench(text) {
  const s = String(text || "").trim();
  if (!s) return false;
  if (FR_STRONG_RE.test(s)) return true;
  const fr = (s.match(FR_WORD_RE) || []).length;
  const en = (s.match(EN_WORD_RE) || []).length;
  return fr >= 2 && fr > en;
}

function clip(raw, max) {
  if (raw.length <= max) return raw;
  return `${raw.slice(0, Math.max(1, max - 1)).trimEnd()}…`;
}

/** « On 24 June, Spanish waters. » → « Spanish waters ». */
export function enTitleFromFacts(text) {
  let s = String(text || "").trim();
  if (!s) return "";
  s = s.split(/(?<=[.!?])\s+/)[0] || s;
  s = s
    .replace(/^(?:on \d{1,2} \w+(?: \d{4})?|the next day|then|later|that day|the same day)\s*,\s*/i, "")
    .replace(/^(?:\w+ (?:miles|nm) away|at \w+ miles)\s*,\s*/i, "")
    .replace(/[.!?…]+$/, "")
    .trim();
  const cut = s.search(/[:;]/);
  if (cut > 8) s = s.slice(0, cut).trim();
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function bubbleTitle(card, max = EVENT_BUBBLE_TITLE_MAX, lang = "fr") {
  const stored = String(card?.title || card?.kind || "").trim();
  if (!isEnLang(lang)) return clip(stored, max);
  const raw = localizeStoredTitle(stored, lang);
  if (raw !== stored) return clip(raw, max);
  const kind = String(card?.kind || "");
  // Nom propre (port, projet, jeu de données) : jamais traduit.
  if (EN_KEEP_TITLE_KINDS.has(kind)) {
    if (!looksFrench(raw) || kind === "stop" || kind === "project" || kind === "sci") return clip(raw, max);
  }
  const text = String(card?.text || "").trim();
  const derived = text && !looksFrench(text) ? enTitleFromFacts(text) : "";
  if (derived && !looksFrench(derived)) return clip(derived, max);
  if (!looksFrench(raw) && !FR_TITLE_RE.test(raw) && raw !== kind) return clip(raw, max);
  return clip(EN_KIND_TITLE[kind] || "Along the route", max);
}

export function bubbleFacts(card, lang = "fr") {
  const text = String((isEnLang(lang) && card?.text_en) || card?.text || "").trim();
  if (!text) return "";
  // Contenu de données seulement en français : masqué en EN (jamais traduit ici).
  if (isEnLang(lang) && looksFrench(text)) return "";
  const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  return sentences.slice(0, 2).join(" ");
}

export function bubbleKindIcon(card) {
  return KIND_ICON[card?.kind] || "•";
}

export function bubbleChips(card) {
  const facts = card?.facts && typeof card.facts === "object" ? card.facts : {};
  const src = { ...facts, ...card };
  const chips = [];
  const wind = Number(src.windKnots ?? src.windKn ?? src.maxWindKnots);
  const hs = Number(src.hs ?? src.maxHs);
  const days = Number(src.daysAtQuay ?? src.quayDays);
  if (Number.isFinite(wind)) chips.push({ id: "wind", kn: Math.round(wind) });
  if (Number.isFinite(hs)) chips.push({ id: "hs", m: hs });
  if (Number.isFinite(days) && days > 0) chips.push({ id: "quay", n: Math.round(days) });
  return chips;
}

function eventMs(ev, chapter, plan) {
  const raw = ev?.card?.at || ev?.t || ev?.at || "";
  const parsed = Date.parse(raw);
  if (Number.isFinite(parsed)) return parsed;
  if (plan?.timeAt && chapter && ev) return plan.timeAt(chapter.idx, ev.charIdx);
  return null;
}

/** Score bulle : 1 / 2 / 3, sinon inféré du kind (script local sans score). */
export function bubbleScore(ev) {
  const n = Number(ev?.score ?? ev?.card?.score);
  if (n === 1 || n === 2 || n === 3) return n;
  const kind = ev?.kind || ev?.card?.kind;
  if (kind === "stop" || kind === "wx") return 3;
  if (kind === "zee" || kind === "sci") return 2;
  if (kind === "amp" || kind === "climo") return 1;
  return 0;
}

/** ≥ 2 : tout de suite. Score 1 : quand la somme des non-montrés atteint 3. */
export function shouldShowFilmEvent(score, pendingScores = []) {
  const s = Number(score) || 0;
  if (s >= BUBBLE_SCORE_SHOW) return true;
  const sum = pendingScores.reduce((n, x) => n + (Number(x) || 0), 0) + s;
  return sum >= BUBBLE_SCORE_SUM;
}

export function filmEventCard(ev, lang = "fr") {
  if (!ev) return null;
  const card = ev.card && typeof ev.card === "object" ? ev.card : {};
  const title = localizeStoredTitle(card.title || ev.title || ev.kind || "", lang);
  const candidate = (isEnLang(lang) && (card.text_en || ev.fact_en)) || card.text || ev.fact || "";
  const text = isEnLang(lang) && looksFrench(candidate) ? "" : candidate;
  return {
    ...card,
    id: card.id || ev.id,
    key: card.key || ev.id || card.key,
    kind: card.kind || ev.kind,
    title,
    text,
    score: ev.score ?? card.score,
    lane: card.lane || "now",
  };
}

export function applyBubbleClose(currentCard) {
  return { card: null, closedId: bubbleId(currentCard) || true };
}

export function isBubbleSuppressed(closedId, nextCard) {
  return Boolean(closedId && nextCard && bubbleId(nextCard) === closedId);
}

/**
 * Une seule candidature à la fois : score ≥ 2, ou somme des scores
 * non montrés depuis 20 s ≥ 3.
 */
export class FilmEventScoreGate {
  constructor({ now = () => Date.now() } = {}) {
    this.now = now;
    this.pending = [];
    this.accepted = new Set();
  }

  reset() {
    this.pending = [];
    this.accepted = new Set();
  }

  accept(ev) {
    if (!ev) return null;
    const id = ev.id || bubbleId(ev.card) || bubbleId(ev);
    if (id && this.accepted.has(id)) return ev;
    const t = this.now();
    this.pending = this.pending.filter((p) => t - p.t <= BUBBLE_SCORE_WINDOW_MS);
    const score = bubbleScore(ev);
    const pendingScores = this.pending.map((p) => p.score);
    if (!shouldShowFilmEvent(score, pendingScores)) {
      if (score > 0 && id && !this.pending.some((p) => p.id === id)) {
        this.pending.push({ id, score, t });
      }
      return null;
    }
    if (id) this.accepted.add(id);
    this.pending = [];
    return ev;
  }
}

/** Voix : dernier événement dont `charIdx` est franchi. Sans voix : à la date. */
export function pickFilmEvent({
  chapter,
  charIdx = 0,
  tMs = null,
  voiceLed = false,
  plan = null,
} = {}) {
  const events = chapter?.events || [];
  if (!events.length) return null;
  let best = null;
  for (const ev of events) {
    if (voiceLed) {
      if ((Number(ev.charIdx) || 0) <= charIdx) best = ev;
      continue;
    }
    const at = eventMs(ev, chapter, plan);
    if (at != null && tMs != null) {
      if (at <= tMs) best = ev;
    } else if ((Number(ev.charIdx) || 0) <= charIdx) {
      best = ev;
    }
  }
  return best;
}

/**
 * Une seule carte à la fois, minimum 3 s, Échap la ferme sans toucher au film.
 * `now` est injectable (faux timers).
 */
export class EventBubbleGate {
  constructor({ now = () => Date.now() } = {}) {
    this.now = now;
    this.card = null;
    this.since = 0;
    this.pending = undefined;
    this.hasPending = false;
    this.dismissed = null;
  }

  reset() {
    this.card = null;
    this.since = 0;
    this.pending = undefined;
    this.hasPending = false;
    this.dismissed = null;
  }

  dismiss() {
    this.dismissed = bubbleId(this.card);
    this.card = null;
    this.since = this.now();
    this.pending = undefined;
    this.hasPending = false;
    return null;
  }

  tick() {
    if (!this.hasPending) return this.card;
    if (this.now() - this.since < EVENT_BUBBLE_MIN_MS) return this.card;
    this.card = this.pending;
    this.since = this.now();
    this.pending = undefined;
    this.hasPending = false;
    return this.card;
  }

  propose(candidate) {
    this.tick();
    const id = bubbleId(candidate);
    if (candidate && this.dismissed && id === this.dismissed) return this.card;
    if (candidate && id !== this.dismissed) this.dismissed = null;
    if (!candidate) return this.card;
    if (bubbleId(this.card) === id) return this.card;
    if (this.card && this.now() - this.since < EVENT_BUBBLE_MIN_MS) {
      this.pending = candidate;
      this.hasPending = true;
      return this.card;
    }
    this.card = candidate;
    this.since = this.now();
    this.pending = undefined;
    this.hasPending = false;
    return this.card;
  }
}

export function followPopupToMarker(popup, marker) {
  if (!popup || !marker) return null;
  const ll = marker.getLatLng();
  popup.setLatLng(ll);
  return popup.getLatLng();
}

export function publishEventBubble(card) {
  if (typeof window === "undefined") return;
  window.__naviguideEventBubble = card || null;
  window.__naviguideScene?.eventBubble?.setCard(card || null);
}
