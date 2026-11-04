import { reviewLeg } from "../engine/planReview.js";
import { entryNmFrom, momentNearest } from "../hooks/useMomentJournal.js";
import frDict from "../i18n/fr.js";
import enDict from "../i18n/en.js";
import { displayStopName } from "../utils/stopLabels.js";
import { lookup as lookupToponym, sheetLabel } from "../engine/toponyms.js";
import { localizePlaceName } from "../utils/placeNames.js";

const MONTHS_SHORT = {
  fr: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

export const ICI_TABS = [
  { id: "now", testId: "ici-tab-now", labelKey: "iciNowTab" },
  { id: "story", testId: "ici-tab-story", labelKey: "iciStoryTab" },
  { id: "journal", testId: "ici-tab-journal", labelKey: "iciJournalTab" },
  { id: "review", testId: "ici-tab-review", labelKey: "planReviewTitle" },
];

const TRACER_TAB_IDS = ["review", "story"];
const FOLLOW_CUSTOM_TAB_IDS = ["review", "journal", "story"];

/** Tracer = simulation (Berry) ou drawn (brouillon / ma route). */
export function isTracerIciMode(mode) {
  return mode === "simulation" || mode === "drawn";
}

export function isFollowCustomIci(mode, { routeSource } = {}) {
  return mode === "follow" && routeSource === "custom";
}

/**
 * Suivre × Berry : Maintenant · Récit · Journal · Revue du plan.
 * Suivre × ma route (DM8C, option A) : Revue du plan · Journal · Récit ;
 * Maintenant masqué (pas de « maintenant » sur une horloge que je choisis).
 * Tracer : Revue du plan · Récit seulement.
 * Les onglets masqués restent dans ICI_TABS : hidden, pas supprimés.
 */
export function visibleIciTabs(mode, { routeSource } = {}) {
  if (isTracerIciMode(mode)) {
    return TRACER_TAB_IDS.map((id) => ICI_TABS.find((tab) => tab.id === id)).filter(Boolean);
  }
  if (isFollowCustomIci(mode, { routeSource })) {
    return FOLLOW_CUSTOM_TAB_IDS.map((id) => ICI_TABS.find((tab) => tab.id === id)).filter(Boolean);
  }
  return ICI_TABS;
}

/**
 * Onglets masqués mais encore dans le DOM (hidden), pour les specs qui
 * cliquent par testid sans les montrer à l'écran.
 */
export function hiddenIciTabs(mode, { routeSource } = {}) {
  if (isTracerIciMode(mode)) {
    return ICI_TABS.filter((tab) => tab.id === "now" || tab.id === "journal");
  }
  if (isFollowCustomIci(mode, { routeSource })) {
    return ICI_TABS.filter((tab) => tab.id === "now");
  }
  return [];
}

/** Onglet ouvert à l'entrée du mode : Revue en Tracer et Suivre × ma route. */
export function defaultIciTab(mode, { routeSource } = {}) {
  if (isTracerIciMode(mode) || isFollowCustomIci(mode, { routeSource })) return "review";
  return "now";
}

/**
 * En Tracer, la Revue du plan sert aussi le contenu de Maintenant
 * (briefing, jambe, escale, Demander conseil) : les onglets sont masqués,
 * pas les surfaces (anti-régression visuelle).
 * En Suivre × ma route : Maintenant n'est pas servi (option A).
 */
export function servesNowContent(view, mode, { routeSource } = {}) {
  if (isFollowCustomIci(mode, { routeSource })) return false;
  if (view === "now") return true;
  return isTracerIciMode(mode) && view === "review";
}

const EVENT_TYPE_LABEL = {
  fr: {
    amp: "Aire marine protégée",
    mpa: "Aire marine protégée",
    cyclone: "Cyclone",
    marina: "Marina",
    port: "Port",
    station: "Station croisée",
    science: "Station croisée",
    sci: "Station croisée",
    stop: "Escale",
    escale: "Escale",
    entry: "Formalités d’entrée",
    poe: "Ports d’entrée",
    zee: "ZEE",
  },
  en: {
    amp: "Marine protected area",
    mpa: "Marine protected area",
    cyclone: "Cyclone",
    marina: "Marina",
    port: "Port",
    station: "Station passed",
    science: "Station passed",
    sci: "Station passed",
    stop: "Stopover",
    escale: "Stopover",
    entry: "Entry formalities",
    poe: "Ports of entry",
    zee: "EEZ",
  },
};

const TYPE_ONLY_TITLES = new Set([
  "Aire marine protégée",
  "Marine protected area",
  "Cyclone",
  "Marina",
  "Port",
  "Station croisée",
  "Station passed",
  "Fiche science",
  "Science sheet",
  "Formalités d'entrée",
  "Formalités d’entrée",
  "Entry formalities",
  "Escale",
  "Stopover",
]);

const NAMED_EVENT_KINDS = new Set([
  "amp", "mpa", "cyclone", "marina", "port", "station", "science", "sci", "stop", "escale", "entry", "poe", "zee",
]);

const TITLE_EN = {
  "Formalités d'entrée": "Entry formalities",
  "Formalités d’entrée": "Entry formalities",
  "Aire marine protégée": "Marine protected area",
  "Station croisée": "Station passed",
  "Escale": "Stopover",
  AMP: "Marine protected area",
  ZEE: "EEZ",
};

const ZEE_ADJ_EN = {
  espagnole: "Spanish",
  française: "French",
  portugaise: "Portuguese",
  italienne: "Italian",
  marocaine: "Moroccan",
  britannique: "British",
  canadienne: "Canadian",
  américaine: "American",
  mexicaine: "Mexican",
  chilienne: "Chilean",
  argentine: "Argentine",
  brésilienne: "Brazilian",
  australienne: "Australian",
  japonaise: "Japanese",
  chinoise: "Chinese",
  indienne: "Indian",
  norvégienne: "Norwegian",
  russe: "Russian",
  turque: "Turkish",
  grecque: "Greek",
  tunisienne: "Tunisian",
  algérienne: "Algerian",
  cubaine: "Cuban",
  colombienne: "Colombian",
  péruvienne: "Peruvian",
  panaméenne: "Panamanian",
  vénézuélienne: "Venezuelan",
  sénégalaise: "Senegalese",
  madagascane: "Malagasy",
  "néo-zélandaise": "New Zealand",
};

const NAMELESS_FACT = /traces de cyclone|cyclone tracks|saison cyclonique|cyclone season|ce mois-ci|this month/i;

function inferKindFromTitle(title) {
  const raw = String(title || "").trim().toLowerCase();
  if (/aire marine|marine protected|^amp\b/.test(raw)) return "amp";
  if (/zone économique|exclusive economic|\beez\b|\bzee\b/.test(raw)) return "zee";
  if (/formalit|entry formalit|ports? d['’]entr|ports? of entry/.test(raw)) return "entry";
  if (/^escale\b|^stopover\b/.test(raw)) return "stop";
  if (raw === "cyclone") return "cyclone";
  if (raw === "marina") return "marina";
  if (/station/.test(raw)) return "station";
  return "";
}

export function localizeStoredTitle(title, lang) {
  const raw = String(title || "").trim().replace(/\([^)]*\)/g, (part) => localizePlaceName(part, lang));
  if (!raw || lang !== "en") return raw;
  if (TITLE_EN[raw]) return TITLE_EN[raw];
  if (/^AMP\b/i.test(raw)) return raw.replace(/^AMP\b/i, "Marine protected area");
  if (/aire marine/i.test(raw)) {
    return raw
      .replace(/aire marine protégée/gi, "Marine protected area")
      .replace(/\baire marine\b/gi, "Marine protected area");
  }
  const zee = /^(?:Entrée dans\s+)?Zone économique exclusive\s+(.+)$/i.exec(raw);
  if (zee) {
    const prefix = /^Entrée dans/i.test(raw) ? "Entering " : "";
    let rest = zee[1].trim();
    const paren = /^(.*?)\s*(\([^)]+\))\s*$/.exec(rest);
    let adj = rest;
    let extra = "";
    if (paren) {
      adj = paren[1].trim();
      extra = ` ${paren[2]}`;
    }
    // Toponym table first: « samoane », « (Polynésie française) » or
    // « (Saint-Vincent-et-les-Grenadines) » must not leak into the EN UI.
    const row = lookupToponym(raw) || lookupToponym(paren ? paren[2].slice(1, -1) : adj) || lookupToponym(adj);
    if (row) {
      const label = sheetLabel(row.fr || raw, "en");
      if (label && label !== "EEZ") return `${prefix}${label}`;
    }
    const enAdj = ZEE_ADJ_EN[adj.toLowerCase()];
    if (enAdj) return `${prefix}${enAdj} EEZ${extra}`;
    return `${prefix}Exclusive economic zone ${adj}${extra}`;
  }
  if (/zone économique exclusive/i.test(raw)) {
    return raw.replace(/zone économique exclusive/gi, "Exclusive economic zone").replace(/\bZEE\b/g, "EEZ");
  }
  const zeeShort = /^ZEE\b\s*(.*)$/.exec(raw);
  if (zeeShort) {
    const rest = zeeShort[1].trim();
    const row = rest ? lookupToponym(rest) : null;
    const label = row ? sheetLabel(row.fr || rest, "en") : "";
    if (label && label !== "EEZ") return label;
    return rest ? `EEZ ${rest}` : "EEZ";
  }
  const escale = /^(?:Escale|Stopover)\s+(.+)$/i.exec(raw);
  if (escale) return `Stopover ${escale[1]}`;
  return raw;
}

function stripTypePrefix(name, type) {
  const n = String(name || "").trim();
  if (!n) return "";
  const exact = [type, "Escale", "Stopover", "Station croisée", "Station passed",
    "Formalités d'entrée", "Formalités d’entrée", "Entry formalities",
    "Aire marine protégée", "Marine protected area"];
  if (exact.some((p) => p && n.toLowerCase() === String(p).toLowerCase())) return "";
  const escale = /^(?:Escale|Stopover)\s+(.+)$/i.exec(n);
  return escale ? escale[1].trim() : n;
}

/**
 * The official journal is built in French. Live GET /ici/moment follows `lang`.
 * Prefer the live moment for alerts / here / around so EN is not a FR leftover.
 */
/** Clock-now leg replaces the pearl/journal leg. Unknown numbers stay absent. */
export function withNowLeg(shown, nowLeg) {
  if (!nowLeg || typeof nowLeg !== "object") return shown;
  const from = nowLeg.from || nowLeg.fromStop;
  const to = nowLeg.to || nowLeg.toStop;
  if (!from && !to) return shown;
  const leg = {};
  if (from) leg.from = from;
  if (to) leg.to = to;
  const kn = Number(nowLeg.kn ?? nowLeg.speedKnots);
  if (Number.isFinite(kn) && kn > 0) leg.kn = kn;
  const left = nowLeg.remainingNm ?? nowLeg.nmRemainingToStop;
  if (left != null && Number.isFinite(Number(left))) leg.remainingNm = Number(left);
  const day = Number(nowLeg.day);
  if (Number.isFinite(day) && day > 0) leg.day = Math.trunc(day);
  const base = shown && typeof shown === "object" ? shown : {};
  return { ...base, leg };
}

export function displayIciFrame(moment, journalEntries, mode) {
  // The journal entry for where the boat is, not for the closest date.
  const journalHit = mode === "follow" && moment
    ? momentNearest(journalEntries, { t: moment?.t, pos: moment?.pos })
    : null;
  const timeline = journalHit || moment;
  return {
    shown: timeline,
    alerts: (moment?.alerts?.length ? moment.alerts : timeline?.alerts) || [],
    here: moment?.here?.sentences?.length ? moment.here : (timeline?.here || moment?.here),
    around: moment?.around?.length ? moment.around : (timeline?.around || []),
    sources: moment?.sources?.length ? moment.sources : (timeline?.sources || []),
  };
}

/**
 * Pendant le film, « Autour du bateau » et les alertes suivent le bateau du
 * film, pas le direct (gelé pendant la lecture : Fineveke restait affiché à
 * La Rochelle comme à Papeete). Source : le moment du journal le plus proche
 * de la position du film, par la position seule (le stock peut être daté sur
 * un autre planning). Au-delà de REPLAY_AROUND_MAX_NM : rien plutôt qu'un lieu
 * faux.
 */
export const REPLAY_AROUND_MAX_NM = 30;

function momentContentSize(m) {
  return (Array.isArray(m?.around) ? m.around.length : 0) + (Array.isArray(m?.alerts) ? m.alerts.length : 0);
}

export function replayMomentAt(journalEntries, at, maxNm = REPLAY_AROUND_MAX_NM) {
  if (!at || !Number.isFinite(Number(at.lat)) || !Number.isFinite(Number(at.lon))) return null;
  let best = null;
  let bestNm = Infinity;
  for (const row of Array.isArray(journalEntries) ? journalEntries : []) {
    const nm = entryNmFrom(row, at);
    if (!(nm <= maxNm)) continue;
    const m = row?.moment || row;
    // Même escale à moins d'un demi-mille : garder le moment qui a quelque chose à dire.
    if (nm < bestNm - 0.5 || (Math.abs(nm - bestNm) <= 0.5 && momentContentSize(m) > momentContentSize(best))) {
      best = m;
      bestNm = Math.min(nm, bestNm);
    }
  }
  return best;
}

export function replayIciFrame(moment, journalEntries, at, maxNm = REPLAY_AROUND_MAX_NM) {
  const hit = replayMomentAt(journalEntries, at, maxNm);
  return {
    shown: moment,
    alerts: Array.isArray(hit?.alerts) ? hit.alerts : [],
    here: moment?.here,
    around: Array.isArray(hit?.around) ? hit.around : [],
    sources: moment?.sources?.length ? moment.sources : (hit?.sources || []),
  };
}

function yearIn(text) {
  const m = String(text || "").match(/\b((?:19|20)\d{2})\b/);
  return m ? m[1] : "";
}

/** Nom porté par le fait serveur — jamais inventé, jamais une phrase générique. */
export function nameFromJournalFact(fact) {
  const s = String(fact || "").trim();
  if (!s || NAMELESS_FACT.test(s)) return "";
  const beforeNm = s.match(/^(.+?)\s+\([\d.,]+\s*nm\)/i);
  if (beforeNm) return beforeNm[1].trim();
  const namedYear = s.match(/^(?:Cyclone\s+)?([^.(]{2,60}?)\s+\((?:19|20)\d{2}\)\s*$/i);
  if (namedYear) return s.replace(/^Cyclone\s+/i, "").trim();
  const beforeColon = s.match(/^([^:]{2,60})\s*:/);
  if (beforeColon && !/^(vent|wind|hs|reste|left|remaining)/i.test(beforeColon[1].trim())) {
    return beforeColon[1].trim();
  }
  if (!/[.!?]$/.test(s) && s.length <= 60 && !/^\d/.test(s) && !/\bkn\b|\bHs\b/i.test(s)) {
    return s;
  }
  return "";
}

function normFact(value) {
  return String(value ?? "")
    .normalize("NFC")
    .replace(/[’`]/g, "'")
    .replace(/\s+/g, " ")
    .replace(/[\s.·:;,–—-]+$/u, "")
    .trim()
    .toLowerCase();
}

/**
 * Fact key: what the item says (type and value), not where it was stored.
 * The value is the title and the fact together, so two protected areas with
 * the same generic fact stay two items.
 */
export function factKey(item) {
  if (!item) return "";
  const kind = String(item.kind || item.type || "").toLowerCase();
  const title = normFact(item.title || item.name);
  const fact = normFact(item.fact || item.text);
  if (!title && !fact) return "";
  return `${kind}|${title}|${fact === title ? "" : fact}`;
}

/** Keeps the first item for each fact key (« haute mer : aucune ZEE » once). */
export function dedupeFacts(items) {
  const seen = new Set();
  const out = [];
  for (const item of Array.isArray(items) ? items : []) {
    const key = factKey(item);
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    out.push(item);
  }
  return out;
}

function splitSentences(text) {
  return String(text ?? "")
    .split(/\n+|(?<=[.!?…])\s+/u)
    .map(normFact)
    .filter(Boolean);
}

/**
 * Server « here » sentences not already said elsewhere in the tab: the
 * briefing paragraph, an alert or an item around. The briefing and the
 * server word the same fact the same way (« haute mer : aucune ZEE »), and
 * they are free text, not items: `dedupeFacts` never saw them.
 */
export function sentencesNotShown(sentences, shownTexts = []) {
  const list = Array.isArray(sentences) ? sentences : [];
  const keep = keptSentences(list, shownTexts);
  return list.filter((_, i) => keep[i]);
}

/** Same rule as `sentencesNotShown`, as one boolean per sentence (in order). */
export function keptSentences(sentences, shownTexts = []) {
  const seen = new Set();
  for (const text of Array.isArray(shownTexts) ? shownTexts : [shownTexts]) {
    for (const part of splitSentences(text)) seen.add(part);
  }
  return (Array.isArray(sentences) ? sentences : []).map((sentence) => {
    const parts = splitSentences(sentence);
    if (!parts.length || parts.every((part) => seen.has(part))) return false;
    parts.forEach((part) => seen.add(part));
    return true;
  });
}

/** True when two cards / items show the same thing (title or fact). */
export function sameShownMoment(a, b) {
  if (!a || !b) return false;
  if (a.key && b.key && a.key === b.key) return true;
  const ta = normFact(a.title || a.name);
  const tb = normFact(b.title || b.name);
  if (ta && ta === tb) return true;
  const fa = normFact(a.text || a.fact);
  const fb = normFact(b.text || b.fact);
  return Boolean(fa && fa === fb);
}

/** The « around » list without what the Next card already shows. */
export function aroundWithoutShown(around, shownCard) {
  return dedupeFacts(around).filter((item) => !sameShownMoment(item, shownCard));
}

const NO_POE_FOR = /^aucun port d['’]entr[ée]e officiel n['’]est connu pour (.+?)\.?$/i;

/** Stored server facts are French: the entry alert goes through i18n FR / EN. */
/** « (2,7 nm) » stocké en français → « (2.7 nm) » en EN ; « 1,500 nm » (milliers) intact. */
/** Sources line of the Now panel: the « zee » producer reads « EEZ » in English. */
export function localizeSourceTag(tag, lang) {
  const raw = String(tag || "");
  if (lang !== "en") return raw;
  return /^zee$/i.test(raw.trim()) ? "EEZ" : raw;
}

export function enDecimals(text, lang) {
  const raw = String(text ?? "");
  if (lang !== "en" || !raw) return raw;
  return raw.replace(/(\d),(\d{1,2})(?!\d)(?=\s*(?:nm|kn|km|m|d|°C|%)(?![a-z]))/gi, "$1.$2");
}

export function localizeStoredFact(text, lang) {
  const raw = enDecimals(String(text || "").trim(), lang);
  if (!raw) return raw;
  const dict = lang === "en" ? enDict : frDict;
  const m = NO_POE_FOR.exec(raw);
  if (m) {
    const zone = m[1].trim();
    if (/^cette zee$/i.test(zone)) return dict.alertNoPortOfEntry;
    return dict.alertNoPortOfEntryFor.replace("{zone}", localizeStoredTitle(zone, lang));
  }
  return raw;
}

/** A stored title: a known server sentence through i18n, else the title map. */
export function localizeStoredLabel(text, lang) {
  const raw = String(text || "").trim();
  return NO_POE_FOR.test(raw) ? localizeStoredFact(raw, lang) : localizeStoredTitle(raw, lang);
}

export function visibleAlerts(alerts, dismissed) {
  const hide = dismissed instanceof Set ? dismissed : new Set(dismissed || []);
  return dedupeFacts((Array.isArray(alerts) ? alerts : []).filter((a) => a && a.id && !hide.has(a.id)));
}

export function dismissAlert(dismissed, id) {
  const next = new Set(dismissed instanceof Set ? dismissed : dismissed || []);
  if (id) next.add(id);
  return next;
}

export function etaDayLabel(iso, lang = "fr") {
  const stamp = Date.parse(iso || "");
  if (!Number.isFinite(stamp)) return "";
  const d = new Date(stamp);
  const months = MONTHS_SHORT[lang] || MONTHS_SHORT.fr;
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]}`;
}

export function formatNumber(value, lang, digits) {
  if (!Number.isFinite(Number(value))) return "";
  const loc = lang === "en" ? "en-US" : "fr-FR";
  if (digits == null) {
    return Math.round(Number(value)).toLocaleString(loc);
  }
  return Number(value).toLocaleString(loc, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * Revue du plan de MA route : une jambe entre chaque couple de points
 * (milles, jours). Pas de fourchette inventée — seulement si l'horloge
 * porte déjà des dates. Jamais le fixture Berry.
 */
export function legsFromClockMarks(clock, lang = "fr") {
  const marks = (clock?.marks || []).filter((m) => m && String(m.name || "").trim());
  if (marks.length < 2) return [];
  const legs = [];
  for (let i = 0; i < marks.length - 1; i += 1) {
    const a = marks[i];
    const b = marks[i + 1];
    const fromNm = Number(a.filmNm ?? a.nm) || 0;
    const toNm = Number(b.filmNm ?? b.nm) || 0;
    const nm = Math.max(0, toNm - fromNm);
    const hours = Number(b.tHours) - Number(a.tHours);
    const days = Number.isFinite(hours) && hours > 0 ? hours / 24 : 0;
    const depart = Date.parse(a.iso || "");
    const month = Number.isFinite(depart) ? new Date(depart).getUTCMonth() + 1 : null;
    legs.push(reviewLeg({
      from: a.name,
      to: b.name,
      legNm: Math.round(nm) || 0,
      daysAtSea: days > 0 ? Math.max(1, Math.round(days)) : 0,
      departIso: a.iso || "",
      arriveIso: b.iso || "",
      month,
      fromNm,
      toNm,
    }, null, lang));
  }
  return legs;
}

export function formatLegLine(leg, t, lang = "fr") {
  if (!leg || typeof leg !== "object") return "";
  const bits = [];
  if (leg.from && leg.to) bits.push(`${displayStopName(leg.from, lang)} → ${displayStopName(leg.to, lang)}`);
  if (Number.isFinite(Number(leg.day))) bits.push(t("iciLegDay", { n: String(Math.trunc(Number(leg.day))) }));
  if (Number.isFinite(Number(leg.kn))) bits.push(t("iciLegKn", { kn: formatNumber(leg.kn, lang, 1) }));
  if (Number.isFinite(Number(leg.remainingNm))) {
    bits.push(t("iciLegRemaining", { nm: formatNumber(leg.remainingNm, lang) }));
  }
  const p10 = etaDayLabel(leg.eta?.p10, lang);
  const p90 = etaDayLabel(leg.eta?.p90, lang);
  if (p10 && p90) bits.push(t("etaRange", { p10, p90 }));
  return bits.join(" · ");
}

export function regimeColor(regime) {
  if (regime === "hindcast") return "#2dd4bf";
  if (regime === "forecast") return "#38bdf8";
  if (regime === "climatology") return "#c084fc";
  return null;
}

export function formatJournalDate(iso, lang = "fr") {
  const day = etaDayLabel(iso, lang);
  if (!day) return "";
  const stamp = Date.parse(iso || "");
  if (!Number.isFinite(stamp)) return day;
  const d = new Date(stamp);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day} ${hh}:${mm}`;
}

export function formatJournalPos(pos, lang = "fr") {
  const lat = Number(pos?.lat);
  const lon = Number(pos?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "";
  return `${formatNumber(lat, lang, 1)} · ${formatNumber(lon, lang, 1)}`;
}

export function journalChangeLabel(entry, lang = "fr") {
  const changes = (Array.isArray(entry?.changes) ? entry.changes : [])
    .filter((c) => c && c.title)
    .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0));
  const change = changes[0];
  if (!change) return "";
  const stored = String(change.title || "").trim();
  if (!stored) return "";
  const title = localizeStoredTitle(stored, lang);
  if (stored.includes(" — ")) {
    const [left, ...rest] = stored.split(" — ");
    const right = rest.join(" — ");
    const loc = localizeStoredTitle(left, lang);
    return right ? `${loc} — ${right}` : loc;
  }
  if (/^Ports d['’]entrée\s*:/i.test(stored)) {
    return lang === "en"
      ? stored.replace(/^Ports d['’]entrée\s*:/i, "Ports of entry:")
      : stored;
  }
  if (/^Ports? of entry\s*:/i.test(stored)) return stored;

  const rawKind = String(change.kind || "");
  const inferred = inferKindFromTitle(stored) || inferKindFromTitle(title);
  const kind = NAMED_EVENT_KINDS.has(rawKind)
    ? rawKind
    : (rawKind === "alert-on" || rawKind === "alert-off" || !rawKind ? inferred : rawKind);
  const labels = EVENT_TYPE_LABEL[lang] || EVENT_TYPE_LABEL.fr;
  const type = labels[kind] || (TYPE_ONLY_TITLES.has(stored) || TYPE_ONLY_TITLES.has(title) ? title : "");
  if (kind === "zee" && /EEZ|exclusive economic/i.test(title)) return title;
  if (!type) return title;

  let name = (TYPE_ONLY_TITLES.has(stored) || TYPE_ONLY_TITLES.has(title)) ? "" : title;
  name = stripTypePrefix(name, type);
  if (name && name.toLowerCase() === type.toLowerCase()) name = "";
  if (!name) name = nameFromJournalFact(change.fact);
  name = stripTypePrefix(name, type);
  if (name && name.toLowerCase() === type.toLowerCase()) name = "";

  if (kind === "cyclone") {
    if (NAMELESS_FACT.test(String(change.fact || ""))) name = nameFromJournalFact(change.fact);
    const year = yearIn(change.fact) || yearIn(name);
    if (name && year && !name.includes(year)) name = `${name} (${year})`;
  }

  if (type && name) return `${type} — ${name}`;
  return type || title;
}

export function formatJournalLine(entry, lang = "fr") {
  return [formatJournalDate(entry?.t, lang), formatJournalPos(entry?.pos, lang), journalChangeLabel(entry, lang)]
    .filter(Boolean)
    .join(" · ");
}

export function seekJournalEntry(onSeek, entry) {
  const t = entry?.t;
  if (typeof onSeek === "function" && t) onSeek(t);
}
