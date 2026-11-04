/**
 * Carte du moment — ce que le visiteur voit pendant que le bateau avance.
 *
 * Deux voies, une file chacune (arbitrage du porteur, 19 sept. 2026) :
 *  - NOW (« à bord, maintenant ») : sécurité et décisions — coup de vent,
 *    repli, haut-fond, cyclone, entrée / sortie de ZEE, port d’entrée, météo
 *    qui change le plan, escale (arrivée / départ), **climatologie** et
 *    **balisage**. Une carte à la fois ; les alertes passent devant ;
 *    fermable ; en lecture une nouvelle carte remplace l’ancienne après
 *    quelques secondes, et une carte laissée loin derrière la tête de
 *    lecture n’est plus montrée.
 *  - FREE (« pendant ce temps, autour du bateau ») : information — fiches
 *    science, projets, image satellite, **câbles**, **aires marines
 *    protégées**, digests groupés, événements « later » atteints par la tête
 *    de lecture. Visible seulement quand aucune carte NOW n’est posée ; tourne,
 *    boucle sur les fiches du sac.
 *
 * Fonctions pures (jamais de mutation de l’état précédent : StrictMode peut
 * rejouer un updater). Pas de HTTP, pas de timer : le hook passe `nowMs`.
 * Le texte vient de `phraseForEvent` (phrase de règles du film, récit LLM
 * seulement sur Rédigé) — jamais un chiffre inventé ici.
 */

import { phraseForEvent, satelliteSentence, climatologySentence } from "./iciBriefing.js";
import { placeLabel } from "./briefingLinks.js";
import { formatJournalEntry } from "./journalFormat.js";
import { haversineNm, wrapLon } from "../utils/geo.js";
import { MOMENT_MAX_NM } from "../hooks/useMomentJournal.js";
// A null coordinate is unknown, never 0 (Number(null) === 0).
import { finiteCoord } from "../hooks/useMoment.js";
import { isLandLegNames } from "../utils/berryLegs.js";
import { displayStopName, landLegDistanceClause } from "../utils/stopLabels.js";
import { factKey, localizeStoredFact, localizeStoredTitle, sameShownMoment } from "../components/iciMaintenant.js";
import fr from "../i18n/fr.js";
import enDict from "../i18n/en.js";

export const LANE_NOW = "now";
export const LANE_FREE = "free";

/** Information kinds: never a NOW card, whatever the judge said. */
const INFO_TYPES = new Set([
  "science-hit",
  "project-nearby",
  "satellite-scene",
  "anchorage-ahead",
  "group",
  "amp-enter",
  "amp-ahead",
  "cable-alert",
]);

/** Bag kinds that are decisions for the skipper (NOW lane). */
const NOW_BAG_KINDS = new Set(["aton", "climatology", "piracy"]);

/** Durées d’affichage (ms). Simulation en pause / Suivre sans lecture : pas d’expiration NOW. */
export const TTL = Object.freeze({
  nowSuivreMs: 90_000,
  nowPlayingMs: 14_000,
  /** In playback a newer NOW card may replace the shown one after this. */
  nowReplaceMs: 5_000,
  freeMs: 9_000,
  freeSuivreMs: 14_000,
  freePausedMs: Infinity,
});

export const QUEUE_MAX = Object.freeze({ now: 6, free: 12 });

/** Simulation: an event left this far behind the playhead is history, not a card. */
export const STALE_CARD_NM = 80;

/** FREE loop: a place farther than this from the boat is another sea, not "around". */
export const FREE_STALE_NM = 60;

/** Cap the per-kind information items taken from one bag (same caps as the briefing). */
const BAG_CAPS = Object.freeze({
  marina: 3,
  capitainerie: 2,
  wpi: 2,
  anchorage: 3,
  science: 3,
  project: 3,
  amp: 2,
  aton: 1,
});

function isEn(lang) {
  return String(lang || "").toLowerCase().startsWith("en");
}

function num(n, lang) {
  if (!Number.isFinite(Number(n))) return "";
  const v = Math.round(Number(n) * 10) / 10;
  return isEn(lang) ? String(v) : String(v).replace(".", ",");
}

/**
 * Which lane an event belongs to. `null` = not shown (hidden by the judge,
 * or a « later » event the playhead has not reached yet).
 */
export function classifyMoment(ev, { filmCum = null, mode = "simulation" } = {}) {
  if (!ev || ev.judge === "hide") return null;
  if (INFO_TYPES.has(ev.type)) return reached(ev, filmCum, mode) ? LANE_FREE : null;
  if (ev.promoted) return LANE_FREE;
  if (ev.judge === "now") return LANE_NOW;
  if (ev.judge === "later") return reached(ev, filmCum, mode) ? LANE_FREE : null;
  return null;
}

function reached(ev, filmCum, mode) {
  if (mode === "suivre") return true;
  if (!Number.isFinite(ev.filmCum) || !Number.isFinite(filmCum)) return true;
  return filmCum + 0.5 >= ev.filmCum;
}

/** Simulation only: the card's place on the film is far behind the boat. */
export function isStaleCard(card, { filmCum = null, mode = "simulation" } = {}) {
  if (mode === "suivre") return false;
  if (!card || !Number.isFinite(card.filmCum) || !Number.isFinite(filmCum)) return false;
  return filmCum - card.filmCum > STALE_CARD_NM;
}

/** Distance of the card's place from the boat (nm), or null when unknown. */
export function cardEntityNmFromBoat(card, boat) {
  const lat = finiteCoord(card?.entity?.lat);
  const lon = finiteCoord(card?.entity?.lon);
  if (
    boat
    && Number.isFinite(lat)
    && Number.isFinite(lon)
    && finiteCoord(boat.lat) != null
    && finiteCoord(boat.lon) != null
  ) {
    return haversineNm(lat, wrapLon(lon), finiteCoord(boat.lat), wrapLon(finiteCoord(boat.lon)));
  }
  const nm = Number(card?.entity?.nm);
  return Number.isFinite(nm) ? nm : null;
}

/** FREE: the cited place is farther than FREE_STALE_NM from the boat. */
export function isFreeStale(card, boat, limitNm = FREE_STALE_NM) {
  if (card?.kind === "news") return false;
  const d = cardEntityNmFromBoat(card, boat);
  return d != null && d > limitNm;
}

/** Place the card can point at on the map (same shape as a briefing entity). */
export function entityForEvent(ev) {
  const p = ev?.payload || {};
  const pick = (kind, item) => {
    if (!item || !Number.isFinite(Number(item.lat)) || !Number.isFinite(Number(item.lon))) return null;
    return {
      id: `${kind}:${item.site_id ?? item.id ?? item.name ?? ev.id}`,
      kind,
      name: placeLabel(kind, item),
      rawName: String(item.name || ""),
      lat: Number(item.lat),
      lon: Number(item.lon),
      nm: Number.isFinite(Number(item.nm)) ? Number(item.nm) : null,
      url: item.url || item.visit_url || item.manager_url || null,
      source: item.source || null,
    };
  };
  return pick("marina", p.harbour)
    || pick("poe", p.poe)
    || pick("amp", p.amp)
    || pick("zee", p.zee)
    || null;
}

const KIND_WORDS = Object.freeze({
  marina: ["Marina", "Marina"],
  capitainerie: ["Capitainerie", "Harbour office"],
  wpi: ["Port de commerce (WPI)", "Commercial port (WPI)"],
  anchorage: ["Mouillage", "Anchorage"],
  science: ["Fiche science", "Science sheet"],
  project: ["Projet", "Project"],
  amp: ["Aire marine protégée", "Marine protected area"],
  aton: ["Balisage", "Aid to navigation"],
  satellite: ["Image satellite", "Satellite image"],
  climatology: ["Climatologie", "Climatology"],
  piracy: ["Piraterie", "Piracy"],
  cable: ["Câble sous-marin", "Submarine cable"],
  escale: ["Escale", "Stopover"],
  climo: ["Changement de régime", "Regime change"],
  sci: ["Station croisée", "Station passed"],
  news: ["Veille", "Watch"],
});

/** Journal kinds that become a moment card. */
export const JOURNAL_CARD_KINDS = new Set(["stop", "zee", "amp", "poe", "wx", "note", "climo", "sci", "news"]);

const JOURNAL_TITLE = {
  fr: { stop: "Escale", zee: "ZEE", amp: "Aire marine protégée", poe: "Port d’entrée", wx: "Météo au bateau", note: "Mot du skipper", climo: "Changement de régime", sci: "Station croisée", news: "Veille" },
  en: { stop: "Stopover", zee: "EEZ", amp: "Marine protected area", poe: "Port of entry", wx: "Weather at the boat", note: "Skipper's note", climo: "Regime change", sci: "Station passed", news: "Watch" },
};

function journalDayLabel(iso, lang) {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  return new Date(t).toLocaleDateString(lang === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "long", timeZone: "UTC" });
}

function watchDayLabel(iso, lang) {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  return new Date(t).toLocaleDateString(isEn(lang) ? "en-GB" : "fr-FR", {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

/** Veille : plus visible après J+2. */
export function newsExpired(entry, nowMs = Date.now()) {
  if (!entry) return true;
  const exp = Date.parse(entry.expires || "");
  if (Number.isFinite(exp)) return nowMs >= exp;
  const at = Date.parse(entry.t || "");
  if (!Number.isFinite(at)) return false;
  return nowMs - at >= 3 * 86_400_000;
}

function journalTitleOf(entry, lang) {
  const words = JOURNAL_TITLE[isEn(lang) ? "en" : "fr"];
  if (entry?.title && typeof entry.title === "object") {
    const picked = isEn(lang) ? (entry.title.en || entry.title.fr) : (entry.title.fr || entry.title.en);
    if (picked) return picked;
  }
  if (typeof entry?.title === "string" && entry.title) {
    return localizeStoredTitle(entry.title, isEn(lang) ? "en" : "fr");
  }
  return words[entry?.kind] || entry?.kind || "";
}

function journalEntityKind(entry) {
  if (entry?.entity?.kind) return entry.entity.kind;
  if (entry?.kind === "poe") return "poe";
  if (entry?.kind === "amp") return "amp";
  if (entry?.kind === "sci") return "science";
  if (entry?.kind === "stop") return "escale";
  if (entry?.kind === "news") return "escale";
  return "place";
}

/** Verdict du juge porté par l'événement, la fiche ou le sac. */
export function eventTruth(ev) {
  const p = ev?.payload || {};
  if (ev?.truth) return ev.truth;
  if (p.truth) return p.truth;
  if (p.poe?.truth) return p.poe.truth;
  if (Array.isArray(p.poe)) {
    const hit = p.poe.find((x) => x && x.truth);
    if (hit) return hit.truth;
  }
  return null;
}

export function truthForCard(card, bag) {
  if (card?.truth) return card.truth;
  const url = card?.entity?.url;
  const name = card?.entity?.rawName || card?.entity?.name;
  for (const p of bag?.poe || []) {
    if (!p?.truth) continue;
    if ((url && p.url === url) || (name && p.name === name)) return p.truth;
  }
  return bag?.truth || null;
}

/**
 * Découpe le texte pour barrer les affirmations `unsupported` — jamais
 * les supprimer. Si une phrase n'est pas dans le texte, elle est ajoutée
 * barrée à la suite.
 */
export function strikeParts(text, unsupported) {
  const src = String(text || "");
  const phrases = (unsupported || [])
    .filter((p) => typeof p === "string" && p.trim())
    .map((p) => p.trim())
    .sort((a, b) => b.length - a.length);
  if (!src && !phrases.length) return [];
  if (!phrases.length) return src ? [{ text: src, strike: false }] : [];

  const walk = (chunk) => {
    if (!chunk) return [];
    let best = null;
    const lower = chunk.toLowerCase();
    for (const p of phrases) {
      const i = lower.indexOf(p.toLowerCase());
      if (i < 0) continue;
      if (!best || i < best.i || (i === best.i && p.length > best.p.length)) {
        best = { i, p: chunk.slice(i, i + p.length) };
      }
    }
    if (!best) return [{ text: chunk, strike: false }];
    return [
      ...walk(chunk.slice(0, best.i)),
      { text: best.p, strike: true },
      ...walk(chunk.slice(best.i + best.p.length)),
    ].filter((part) => part.text);
  };

  const parts = walk(src);
  const lowerSrc = src.toLowerCase();
  for (const p of phrases) {
    if (lowerSrc.includes(p.toLowerCase())) continue;
    parts.push({ text: p, strike: true, extra: true });
  }
  return parts.length ? parts : [{ text: src, strike: false }];
}

export function formatTruthDate(iso, lang = "fr") {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  return new Date(t).toLocaleDateString(isEn(lang) ? "en-GB" : "fr-FR", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** A moment card (NOW lane) from a journal line — the text the journal already formats. */
export function cardFromJournalEntry(entry, lang = "fr", nowMs = Date.now()) {
  if (!entry || !JOURNAL_CARD_KINDS.has(entry.kind)) return null;
  if (entry.kind === "news" && newsExpired(entry, nowMs)) return null;
  const f = formatJournalEntry(entry, lang);
  const when = entry.kind === "news" ? watchDayLabel(entry.t, lang) : journalDayLabel(entry.t, lang);
  const title = entry.kind === "news"
    ? `${entry.name || journalTitleOf(entry, lang)}${when ? ` · ${isEn(lang) ? "watch of" : "veille du"} ${when}` : ""}`
    : journalTitleOf(entry, lang);
  const hasPos = Number.isFinite(entry.lat) && Number.isFinite(entry.lon);
  const given = entry.entity && typeof entry.entity === "object" ? entry.entity : null;
  const lat = Number.isFinite(given?.lat) ? given.lat : entry.lat;
  const lon = Number.isFinite(given?.lon) ? given.lon : entry.lon;
  return {
    key: `replay:${entry.id || `${entry.kind}:${entry.t}`}`,
    lane: entry.kind === "news" ? LANE_FREE : LANE_NOW,
    origin: "journal",
    kind: entry.kind,
    type: `replay-${entry.kind}`,
    severity: entry.kind === "wx" ? "alert" : "info",
    title: entry.kind === "news" ? title : `${title}${when ? ` · ${when}` : ""}`,
    text: f.text,
    facts: entry.facts || null,
    entity: hasPos || (Number.isFinite(lat) && Number.isFinite(lon)) || given?.url || entry.url
      ? {
        id: `replay:${entry.kind}:${entry.name || given?.name || entry.t}`,
        kind: journalEntityKind(entry),
        name: given?.name || entry.name || title,
        rawName: given?.name || entry.name || "",
        lat: Number.isFinite(lat) ? lat : entry.lat,
        lon: Number.isFinite(lon) ? lon : entry.lon,
        nm: Number.isFinite(given?.nm) ? given.nm : (Number.isFinite(entry.nm) ? entry.nm : 0),
        url: given?.url || entry.url || entry.visitUrl || null,
        source: given?.source || entry.basis || null,
      }
      : null,
    whenNm: 0,
    at: entry.t,
    truth: entry.truth || null,
  };
}

export function kindWord(kind, lang) {
  const row = KIND_WORDS[kind];
  return row ? row[isEn(lang) ? 1 : 0] : String(kind || "");
}

function placeItem(kind, item, lang) {
  if (!item || !item.name) return null;
  const name = placeLabel(kind, item, lang);
  const nm = Number.isFinite(Number(item.nm)) ? Number(item.nm) : null;
  const en = isEn(lang);
  const where = nm != null ? (en ? ` at ${num(nm, lang)} nm` : ` à ${num(nm, lang)} nm`) : "";
  const source = item.source ? ` (${item.source})` : "";
  const enrich = item.enrich?.text || item.phrase || "";
  const key = `bag:${kind}:${item.site_id ?? item.id ?? item.osm_id ?? `${item.name}:${Number(item.lat).toFixed(2)}:${Number(item.lon).toFixed(2)}`}`;
  return {
    key,
    lane: NOW_BAG_KINDS.has(kind) ? LANE_NOW : LANE_FREE,
    origin: "bag",
    kind,
    type: kind,
    severity: "info",
    title: kindWord(kind, lang),
    text: `${name}${where}${kind === "science" ? source : ""}.${enrich ? ` ${enrich}` : ""}`,
    entity: {
      id: key,
      kind,
      name,
      rawName: String(item.name),
      lat: Number.isFinite(Number(item.lat)) ? Number(item.lat) : null,
      lon: Number.isFinite(Number(item.lon)) ? Number(item.lon) : null,
      nm,
      url: item.enrich?.url || item.url || item.website || (kind === "amp" ? item.visit_url || item.manager_url : null) || null,
      source: item.source || item.enrich?.source || null,
    },
  };
}

function newsItemFromBag(item, lang, nowMs = Date.now()) {
  if (!item || newsExpired(item, nowMs)) return null;
  const name = item.name || "";
  const when = watchDayLabel(item.t, lang);
  const host = (() => {
    if (!item.url) return item.source || "";
    try { return new URL(item.url).hostname.replace(/^www\./, ""); } catch { return item.source || ""; }
  })();
  const title = `${name}${when ? ` · ${isEn(lang) ? "watch of" : "veille du"} ${when}` : ""}`;
  const text = `${item.text || ""}${host ? ` (${host})` : ""}`.trim();
  if (!text) return null;
  const key = `bag:news:${item.id || `${name}:${item.t}`}`;
  const lat = Number.isFinite(Number(item.lat)) ? Number(item.lat) : (Number.isFinite(Number(item.entity?.lat)) ? Number(item.entity.lat) : null);
  const lon = Number.isFinite(Number(item.lon)) ? Number(item.lon) : (Number.isFinite(Number(item.entity?.lon)) ? Number(item.entity.lon) : null);
  return {
    key,
    lane: LANE_FREE,
    origin: "bag",
    kind: "news",
    type: "news",
    severity: "info",
    title,
    text,
    entity: {
      id: key,
      kind: "escale",
      name,
      rawName: name,
      lat,
      lon,
      nm: 0,
      url: item.url || item.entity?.url || null,
      source: item.source || host || null,
    },
    at: item.t,
    expires: item.expires || null,
  };
}

function fillTpl(tpl, vars) {
  return String(tpl || "").replace(/\{(\w+)\}/g, (_, k) => (vars[k] == null ? "" : String(vars[k])));
}

/** Unique NOW card from `ici().piracy` — gone when the bag has no zone. */
export function piracyCardFromBag(bag, lang = "fr") {
  const p = bag?.piracy;
  if (!p?.name || !p.level) return null;
  const u = isEn(lang) ? enDict : fr;
  const level = String(p.level).toUpperCase();
  const source = p.source || "IMB/UKMTO";
  const text = fillTpl(u.momentPiracyCard, { name: p.name, level, source });
  if (!text) return null;
  return {
    key: `bag:piracy:${p.name}`,
    lane: LANE_NOW,
    origin: "bag",
    kind: "piracy",
    type: "piracy",
    severity: level === "HIGH" ? "alert" : "watch",
    title: null,
    text,
    entity: null,
  };
}

/**
 * Cards in one `ici()` bag: what is around the boat, told one card at a time.
 * Keys are stable per place so a marina met again 3 nm later is not repeated.
 * Balisage, climatologie and piracy go to the NOW lane (decisions), the rest to FREE.
 */
export function infoItemsFromBag(bag, lang = "fr", nowMs = Date.now()) {
  // `nowMs` : l'heure de référence du moment (advanceMoments) — les actualités qui expirent
  // sont jugées à cette heure, pas à l'horloge murale (test L4 devenu rouge le 23 sept. 2026).
  if (!bag) return [];
  const out = [];
  const push = (kind, items) => {
    (items || []).slice(0, BAG_CAPS[kind] ?? 3).forEach((it) => {
      const card = placeItem(kind, it, lang);
      if (card) out.push(card);
    });
  };
  push("marina", bag.nearby?.marinas);
  push("capitainerie", bag.nearby?.capitaineries);
  push("wpi", bag.nearby?.wpi);
  push("anchorage", bag.nearby?.anchorages);
  push("science", bag.science?.nearby);
  push("project", bag.projects);
  push("amp", bag.amp);
  (bag.news || []).forEach((it) => {
    const card = newsItemFromBag(it, lang, nowMs);
    if (card) out.push(card);
  });
  push("aton", bag.aton?.nearby);

  const scene = bag.satellites?.scene || bag.satellites?.scenes?.[0];
  if (scene?.id) {
    out.push({
      key: `bag:satellite:${scene.id}`,
      lane: LANE_FREE,
      origin: "bag",
      kind: "satellite",
      type: "satellite-scene",
      severity: "info",
      title: kindWord("satellite", lang),
      text: satelliteSentence(bag, lang),
      entity: null,
    });
  }

  const cables = bag.emodnet?.cables;
  if (cables?.nearby === true) {
    const at = bag.at || {};
    out.push({
      key: `bag:cable:${Number(at.lat).toFixed(1)}:${Number(at.lon).toFixed(1)}`,
      lane: LANE_FREE,
      origin: "bag",
      kind: "cable",
      type: "cable-alert",
      severity: "info",
      title: kindWord("cable", lang),
      text: isEn(lang)
        ? "A submarine cable passes here (EMODnet, observation)."
        : "Un câble sous-marin passe ici (EMODnet, observation).",
      entity: null,
    });
  }

  const c = bag.climatology;
  if (c && (c.point || c.wind) && c.month != null) {
    const zone = c.zone || c.point?.zone || c.point?.cell || `${Math.round(Number(bag.at?.lat) / 5) * 5}:${Math.round(Number(bag.at?.lon) / 5) * 5}`;
    out.push({
      key: `bag:climatology:${c.month}:${zone}`,
      lane: LANE_NOW,
      origin: "bag",
      kind: "climatology",
      type: "climatology",
      severity: "info",
      title: kindWord("climatology", lang),
      text: climatologySentence(bag, lang),
      entity: null,
    });
  }

  const piracy = piracyCardFromBag(bag, lang);
  if (piracy) out.push(piracy);

  const boat = bag.at && Number.isFinite(Number(bag.at.lat)) && Number.isFinite(Number(bag.at.lon))
    ? { lat: Number(bag.at.lat), lon: Number(bag.at.lon) }
    : null;
  return out.filter((card) => (
    card.text
    && (card.lane === LANE_NOW || !isFreeStale(card, boat))
  ));
}

function eventKey(ev) {
  return `ev:${ev.stableKey || ev.id}`;
}

function draftedStorySource(ev, written) {
  if (!written || ev?.story?.status !== "ready") return null;
  const engine = String(ev.story.engine || "");
  const source = ev.story.ai_model || ev.story.source || engine || ev.story.nvidia || null;
  if (!source) return null;
  if (engine.endsWith("+local") || String(source).endsWith("+local")) return null;
  return source;
}

export function cardFromEvent(ev, lang = "fr", { written = false } = {}) {
  const lane = ev.promoted || INFO_TYPES.has(ev.type) || ev.judge !== "now" ? LANE_FREE : LANE_NOW;
  return {
    key: eventKey(ev),
    lane,
    origin: "event",
    kind: ev.type,
    type: ev.type,
    severity: ev.severity || "info",
    title: null,
    text: phraseForEvent(ev, lang, { written }),
    entity: entityForEvent(ev),
    whenNm: ev.whenNm ?? null,
    filmCum: ev.filmCum ?? null,
    storyStatus: ev.story?.status || null,
    storySource: draftedStorySource(ev, written),
    judgeReason: ev.judgeReason || null,
    truth: eventTruth(ev),
  };
}

/**
 * Escale card: written when the leg changes (the boat left a stopover).
 * `leg` = { fromStop, toStop, holdDays, legNm, etaIso } from the film clock.
 */
function isLandEscale(leg) {
  if (leg?.kind === "land" || leg?.vehicle === "land") return true;
  return isLandLegNames(leg?.fromStop, leg?.toStop);
}

export function escaleCard(leg, lang = "fr", { filmCum = null } = {}) {
  if (!leg?.fromStop) return null;
  const en = isEn(lang);
  const fromRaw = String(leg.fromStop);
  const toRaw = leg.toStop ? String(leg.toStop) : null;
  const from = displayStopName(fromRaw, lang);
  const to = toRaw ? displayStopName(toRaw, lang) : null;
  const land = isLandEscale(leg);
  const loc = en ? "en-GB" : "fr-FR";
  const quay = Number.isFinite(leg.holdDays) && leg.holdDays > 0
    ? (en ? ` — ${leg.holdDays} day${leg.holdDays > 1 ? "s" : ""} in port` : ` — ${leg.holdDays} jour${leg.holdDays > 1 ? "s" : ""} à quai`)
    : "";
  const distNm = Number.isFinite(leg.legNm) && leg.legNm > 0.5
    ? leg.legNm
    : (Number.isFinite(leg.filmNm) && leg.filmNm > 0.5 ? leg.filmNm : null);
  let dist = "";
  if (distNm != null) {
    if (land) {
      const clause = landLegDistanceClause(distNm, leg.roadHours, lang);
      dist = clause ? `, ${clause}` : "";
    } else {
      dist = ` (${Math.round(distNm).toLocaleString(loc)} nm)`;
    }
  }
  const eta = !land && leg.etaLabel
    ? (en ? `, expected on ${leg.etaLabel}` : `, arrivée prévue le ${leg.etaLabel}`)
    : "";
  const text = to
    ? (en
      ? `Stopover ${from}${quay}. Departure: heading for ${to}${dist}${eta}.`
      : `Escale ${from}${quay}. Départ : cap sur ${to}${dist}${eta}.`)
    : (en ? `Stopover ${from}${quay}.` : `Escale ${from}${quay}.`);
  return {
    key: `ev:escale:${fromRaw}→${toRaw || ""}`,
    lane: LANE_NOW,
    origin: "event",
    kind: "escale",
    type: "escale-out",
    severity: "watch",
    title: kindWord("escale", lang),
    text,
    entity: Number.isFinite(leg.lat) && Number.isFinite(leg.lon)
      ? { id: `escale:${fromRaw}`, kind: "wpi", name: from, rawName: fromRaw, lat: leg.lat, lon: leg.lon, nm: 0, url: null, source: null }
      : null,
    filmCum,
    whenNm: 0,
  };
}

export function emptyMoments() {
  return {
    now: null,
    nowQueue: [],
    free: null,
    freeQueue: [],
    // Bag cards already shown on this leg: when the queue runs dry, the block
    // loops on them (what is around the boat stays readable), events never repeat.
    freeLoop: [],
    seen: new Set(),
    dismissed: new Set(),
    legId: null,
  };
}

function sortNowQueue(queue) {
  // Alerts first, then in arrival order (stable).
  return queue
    .map((c, i) => [c, i])
    .sort((a, b) => {
      const sa = a[0].severity === "alert" ? 0 : 1;
      const sb = b[0].severity === "alert" ? 0 : 1;
      return sa - sb || a[1] - b[1];
    })
    .map(([c]) => c);
}

function pushCapped(queue, card, max) {
  const next = [...queue, card];
  while (next.length > max) {
    const idx = next.findIndex((c) => c.severity !== "alert");
    next.splice(idx >= 0 ? idx : 0, 1);
  }
  return next;
}

function finiteOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const HASH_LIKE = /^[0-9a-f]{16,}$/i;

function readable(value) {
  const text = String(value || "").trim();
  return HASH_LIKE.test(text) ? "" : text;
}

function officialCard(item, lane, salt, pos) {
  const title = readable(item?.title || item?.name);
  const text = readable(item?.fact || item?.text);
  if (!title && !text) return null;
  const kind = item?.kind || (lane === "now" ? "alert" : "place");
  const label = title || text;
  return {
    key: `${lane}:${salt}:${kind}:${label}`,
    lane,
    type: kind,
    kind,
    title: label,
    text: text || title,
    layer: item?.layer || null,
    source: item?.source || null,
    entity: {
      kind,
      name: label,
      url: item?.url || item?.visit_url || null,
      lat: finiteOrNull(item?.lat ?? pos?.lat),
      lon: finiteOrNull(item?.lon ?? pos?.lon),
    },
  };
}

// Raw codes that a stored change may carry as its title (« grib », « amp »).
const KIND_CODES = {
  grib: "Grib", amp: "Amp", mpa: "Amp", zee: "Zee", eez: "Zee", poe: "Poe",
  marina: "Marina", marinas: "Marina", port: "Port", coast: "Port", wpi: "Port",
  science: "Science", station: "Science", climo: "Climo", climatology: "Climo",
  project: "Project", projects: "Project", layer: "Layer", bathymetry: "Bathymetry",
  capitainerie: "Capitainerie", capitaineries: "Capitainerie", weather: "Weather", wind: "Weather",
};

function kindLabel(code, lang) {
  const key = KIND_CODES[String(code || "").trim().toLowerCase()];
  if (!key) return "";
  const u = isEn(lang) ? enDict : fr;
  return u[`momentKind${key}`] || "";
}

/**
 * A card never shows a raw code: a title that is only the kind or layer code
 * (« grib », « amp ») becomes its label in the reader's language, and a text
 * that only repeats the code is dropped.
 */
export function readableCard(card, item, lang = "fr") {
  if (!card) return card;
  const codes = new Set([card.kind, item?.kind, item?.layer, card.layer].filter(Boolean).map((c) => String(c).toLowerCase()));
  const isCode = (s) => {
    const v = String(s || "").trim().toLowerCase();
    return Boolean(v) && (codes.has(v) || v in KIND_CODES);
  };
  const out = { ...card, entity: { ...(card.entity || {}) } };
  if (isCode(out.title)) {
    const label = kindLabel(out.title, lang) || kindLabel(out.kind, lang) || out.title;
    const realText = isCode(out.text) ? "" : out.text;
    // « amp » + « Pertuis charentais » → the place as title, its type as text;
    // « grib » + « grib » → the type alone.
    out.title = realText || label;
    out.text = label;
    out.entity.name = out.title;
  } else if (isCode(out.text)) {
    out.text = kindLabel(out.text, lang) || out.title;
  }
  return out;
}

/** Moments of the same day as the latest one count as « now » for the position choice. */
export const OFFICIAL_MOMENT_WINDOW_MS = 24 * 3600 * 1000;

function rowTimeMs(row) {
  const t = Date.parse(row?.t);
  return Number.isFinite(t) ? t : null;
}

function rowPos(row) {
  const pos = row?.pos || row?.moment?.pos || null;
  const lat = finiteCoord(pos?.lat);
  const lon = finiteCoord(pos?.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null;
}

/**
 * The current moment: among the moments of the date window (up to `until`),
 * the one closest to the boat. Without a known position, the latest one.
 */
export function pickOfficialMoment(rows, { boat = null, maxNm = MOMENT_MAX_NM } = {}) {
  const list = Array.isArray(rows) ? rows : [];
  const latest = list.at(-1) || null;
  const lat = finiteCoord(boat?.lat);
  const lon = finiteCoord(boat?.lon);
  if (!latest || !Number.isFinite(lat) || !Number.isFinite(lon)) return latest;
  const nearest = (candidates) => {
    let best = null;
    let bestNm = Infinity;
    for (const row of candidates) {
      const pos = rowPos(row);
      if (!pos) continue;
      const nm = haversineNm(pos.lat, wrapLon(pos.lon), lat, wrapLon(lon));
      if (nm <= maxNm && nm <= bestNm) {
        best = row;
        bestNm = nm;
      }
    }
    return best;
  };
  const latestMs = rowTimeMs(latest);
  const window = latestMs == null
    ? [latest]
    : list.filter((row) => {
      const t = rowTimeMs(row);
      return t != null && latestMs - t <= OFFICIAL_MOMENT_WINDOW_MS;
    });
  // The date window first, then any earlier moment near the boat; a moment
  // far from the boat (another territory) is never « now ».
  return nearest(window) || nearest(list) || null;
}

/** Keys under which a card counts as already shown: its fact, its title, its layer. */
function shownKeys(card) {
  const keys = [];
  const fact = factKey(card);
  if (fact) keys.push(`fact:${fact}`);
  const title = factKey({ kind: card.kind, title: card.title });
  if (title) keys.push(`title:${title}`);
  if (card.layer) keys.push(`layer:${card.kind}|${String(card.layer).toLowerCase()}`);
  return keys;
}

function fallbackTitle(current, lang) {
  const u = isEn(lang) ? enDict : fr;
  const here = current?.moment?.here || current?.here || {};
  const zee = here?.zee && typeof here.zee === "object" ? here.zee : null;
  const place = readable(here?.place?.name || here?.name || zee?.name);
  return place ? localizeStoredTitle(place, lang) : u.momentFallbackTitle;
}

function fallbackText(current, lang) {
  const ms = rowTimeMs(current);
  if (ms == null) return "";
  return new Date(ms).toLocaleDateString(isEn(lang) ? "en-GB" : "fr-FR", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

/** Cards for the boat at `until`, from GET /voyage/official/moments. */
export function cardsFromOfficialMoments(entries, { until = null, boat = null, lang = "fr" } = {}) {
  const rows = (Array.isArray(entries) ? entries : []).filter((row) => {
    if (!row?.t) return false;
    if (!until) return true;
    const cut = Date.parse(until);
    const t = Date.parse(row.t);
    if (Number.isFinite(cut) && Number.isFinite(t)) return t <= cut;
    return String(row.t) <= String(until);
  });
  rows.sort((a, b) => String(a.t).localeCompare(String(b.t)));
  const current = pickOfficialMoment(rows, { boat });
  if (!current) return { now: null, freeQueue: [] };
  const pos = current.pos || {};
  const salt = current.signature || current.t;
  const alerts = Array.isArray(current.alerts) ? current.alerts : [];
  const around = [
    ...(Array.isArray(current.around) ? current.around : []),
    ...(Array.isArray(current.changes) ? current.changes : []),
  ];
  const alert = alerts.find((item) => item && (readable(item.title) || readable(item.fact) || readable(item.name))) || null;
  const now = alert ? readableCard(officialCard(alert, "now", salt, pos), alert, lang) : null;
  if (now) now.text = localizeStoredFact(now.text, lang);
  const freeQueue = [];
  // One card per fact, per title and per layer; never the Now card again.
  const seen = new Set(now ? shownKeys(now) : []);
  for (const item of around) {
    const card = readableCard(officialCard(item, "free", salt, pos), item, lang);
    if (!card) continue;
    const keys = shownKeys(card);
    if (keys.some((key) => seen.has(key))) continue;
    keys.forEach((key) => seen.add(key));
    card.text = localizeStoredFact(card.text, lang);
    freeQueue.push(card);
  }
  if (!now && !freeQueue.length) {
    const fallback = officialCard(
      { title: fallbackTitle(current, lang), fact: fallbackText(current, lang), kind: "place" },
      "free",
      salt,
      pos,
    );
    if (fallback) freeQueue.push(fallback);
  }
  return { now, freeQueue };
}

export function pageOfficialCards(built, { hideNow = false, freeIndex = 0 } = {}) {
  const queue = built?.freeQueue || [];
  const index = Number.isFinite(Number(freeIndex)) ? Number(freeIndex) : 0;
  return {
    now: hideNow ? null : (built?.now || null),
    free: queue[index] || null,
  };
}

/** A port card shows only within this distance of that port… */
export const PORT_CARD_NEAR_NM = 30;
/** …or while leaving it / reaching it (sailed / remaining on the leg). */
export const PORT_CARD_PHASE_NM = 30;

/** « Escale La Rochelle (Charente-Maritime) » and « La Rochelle » are one stop. */
export function stopKey(name) {
  return String(name || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/\([^)]*\)/g, " ")
    .replace(/^\s*(escale|stopover|depart|departure|arrivee|arrival)\s*(de|from|a|to)?\s+/i, "")
    .replace(/[’'`-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function sameStop(a, b) {
  const ka = stopKey(a);
  const kb = stopKey(b);
  return Boolean(ka) && ka === kb;
}

function isPortCard(card) {
  return card?.kind === "escale" || card?.type === "escale-out" || card?.kind === "port" || card?.type === "port";
}

/**
 * Whether a port / stopover card still describes where the boat is: near the
 * port, or in the departure / arrival phase of that port. Other cards: true.
 * When neither position nor progress is known, nothing is hidden.
 */
export function portCardIsCurrent(card, { boat = null, leg = null } = {}) {
  if (!isPortCard(card)) return true;
  const name = card?.entity?.rawName || card?.entity?.name || null;
  const done = Number(leg?.doneNm);
  const left = Number(leg?.leftNm);
  const phaseKnown = Number.isFinite(done) || Number.isFinite(left);
  if (name && sameStop(leg?.fromStop, name) && Number.isFinite(done) && done <= PORT_CARD_PHASE_NM) return true;
  if (name && sameStop(leg?.toStop, name) && Number.isFinite(left) && left <= PORT_CARD_PHASE_NM) return true;
  const boatKnown = finiteCoord(boat?.lat) != null && finiteCoord(boat?.lon) != null;
  const portKnown = finiteCoord(card?.entity?.lat) != null && finiteCoord(card?.entity?.lon) != null;
  if (boatKnown && portKnown) return cardEntityNmFromBoat(card, boat) <= PORT_CARD_NEAR_NM;
  return !phaseKnown;
}

/**
 * Now / Free slots. The official moment for this position fills Now.
 * A live safety alert still comes first. The synthetic stopover card does
 * not cover that moment, and does not come back after it is dismissed.
 * A port card far from the boat is not shown, and Now never repeats the
 * card already shown as Next.
 */
export function selectDisplayedMoments({
  eventNow = null,
  eventFree = null,
  officialNow = null,
  officialHasNow = false,
  officialFree = null,
  boat = null,
  leg = null,
} = {}) {
  const current = (card) => (card && portCardIsCurrent(card, { boat, leg }) ? card : null);
  const liveNow = current(eventNow);
  const safety = liveNow
    && liveNow.severity === "alert"
    && liveNow.kind !== "escale"
    && liveNow.type !== "escale-out"
    ? liveNow
    : null;
  const free = current(eventFree) || current(officialFree) || null;
  let now = safety || (officialHasNow ? current(officialNow) : (liveNow || current(officialNow) || null));
  if (now && free && sameShownMoment(now, free)) now = null;
  return { now, free };
}

export function nowTtlMs({ mode, playing }) {
  if (mode === "suivre") return TTL.nowSuivreMs;
  return playing ? TTL.nowPlayingMs : Infinity;
}

export function freeTtlMs({ mode, playing }) {
  if (mode === "suivre") return TTL.freeSuivreMs;
  return playing ? TTL.freeMs : TTL.freePausedMs;
}

function sameText(a, b) {
  return a?.text === b?.text && a?.storyStatus === b?.storyStatus && a?.storySource === b?.storySource;
}

/**
 * One step. Ingests the judged ledger + the current bag (+ an escale card
 * when the leg changed), expires cards, and promotes the next one. Returns
 * the same object when nothing changed so React can skip the render.
 */
export function advanceMoments(prev, {
  events = [],
  bag = null,
  filmCum = null,
  nowMs = Date.now(),
  playing = false,
  mode = "simulation",
  lang = "fr",
  written = false,
  legId = null,
  leg = null,
} = {}) {
  let state = prev || emptyMoments();
  let changed = false;
  // Pure: never mutate `prev.seen` — React (StrictMode) may run an updater
  // twice with the same previous state and keep the second result.
  const seen = new Set(state.seen);
  let nowQueue = state.nowQueue;
  let freeQueue = state.freeQueue;
  let freeLoop = state.freeLoop || [];
  let now = state.now;
  let free = state.free;

  if (legId !== state.legId) {
    // New leg: the ledger restarted; queued cards of the old leg are stale.
    const previousLeg = state.legId;
    state = { ...state, legId };
    nowQueue = [];
    freeQueue = [];
    freeLoop = [];
    free = null;
    changed = true;
    // Changement de jambe : une carte Escale. Première jambe : seulement
    // l’étape terrestre (Saint-Maur → La Rochelle, km par la route).
    if (leg?.fromStop && (previousLeg != null || isLandEscale(leg))) {
      const card = escaleCard(leg, lang, { filmCum });
      if (card && !seen.has(card.key) && !state.dismissed.has(card.key)) {
        seen.add(card.key);
        nowQueue = pushCapped(nowQueue, card, QUEUE_MAX.now);
      }
    }
  }

  // 1. Events → lanes.
  const eventCards = new Map();
  for (const ev of events || []) {
    const lane = classifyMoment(ev, { filmCum, mode });
    if (!lane) continue;
    const card = cardFromEvent(ev, lang, { written });
    const truth = card.truth || truthForCard(card, bag);
    if (truth) card.truth = truth;
    if (!card.text) continue;
    eventCards.set(card.key, card);
    if (seen.has(card.key)) continue;
    if (state.dismissed.has(card.key)) continue;
    if (isStaleCard(card, { filmCum, mode })) continue; // history, not a card
    seen.add(card.key);
    changed = true;
    if (lane === LANE_NOW) nowQueue = pushCapped(nowQueue, card, QUEUE_MAX.now);
    else freeQueue = pushCapped(freeQueue, card, QUEUE_MAX.free);
  }

  // Story text arrives after the card: refresh what is displayed / queued.
  const refresh = (card) => {
    if (!card || card.origin !== "event") return card;
    const fresh = eventCards.get(card.key);
    const truth = fresh?.truth || truthForCard(card, bag) || card.truth || null;
    if (!fresh || (sameText(fresh, card) && truth === card.truth)) {
      if (truth && truth !== card.truth) {
        changed = true;
        return { ...card, truth };
      }
      return card;
    }
    changed = true;
    return { ...card, text: fresh.text, storyStatus: fresh.storyStatus, storySource: fresh.storySource ?? null, truth };
  };
  now = refresh(now);
  free = refresh(free);
  nowQueue = nowQueue.map(refresh);
  freeQueue = freeQueue.map(refresh);

  const boat = bag?.at && Number.isFinite(Number(bag.at.lat)) && Number.isFinite(Number(bag.at.lon))
    ? { lat: Number(bag.at.lat), lon: Number(bag.at.lon) }
    : null;
  const dropFarFree = (list) => {
    if (!boat || !list?.length) return list;
    const next = list.filter((c) => !isFreeStale(c, boat));
    if (next.length !== list.length) changed = true;
    return next;
  };

  // 2. Bag → cards (balisage / climatologie → NOW, the rest → FREE).
  for (const card of infoItemsFromBag(bag, lang, nowMs)) {
    const truth = truthForCard(card, bag);
    const withTruth = truth ? { ...card, truth } : card;
    if (seen.has(withTruth.key)) continue;
    seen.add(withTruth.key);
    if (withTruth.lane === LANE_NOW) nowQueue = pushCapped(nowQueue, { ...withTruth, filmCum }, QUEUE_MAX.now);
    else freeQueue = pushCapped(freeQueue, withTruth, QUEUE_MAX.free);
    changed = true;
  }

  // One piracy card, gone outside the zone (re-enters if the boat comes back).
  const keepPiracy = bag?.piracy?.name ? `bag:piracy:${bag.piracy.name}` : null;
  const piracyGone = (c) => c?.kind === "piracy" && c.key !== keepPiracy;
  if (piracyGone(now)) {
    seen.delete(now.key);
    now = null;
    changed = true;
  }
  nowQueue = nowQueue.filter((c) => {
    if (!piracyGone(c)) return true;
    seen.delete(c.key);
    changed = true;
    return false;
  });
  if (now && now.severity !== "alert" && nowQueue.some((c) => c.kind === "piracy" && c.severity === "alert")) {
    nowQueue = [now, ...nowQueue];
    now = null;
    changed = true;
  }

  // 3. Drop queued cards left behind by the playhead (Simulation).
  const beforeNow = nowQueue.length;
  nowQueue = nowQueue.filter((c) => !isStaleCard(c, { filmCum, mode }));
  const beforeFree = freeQueue.length;
  freeQueue = freeQueue.filter((c) => !isStaleCard(c, { filmCum, mode }));
  if (nowQueue.length !== beforeNow || freeQueue.length !== beforeFree) changed = true;
  // A FREE place more than FREE_STALE_NM from the boat leaves the loop.
  freeQueue = dropFarFree(freeQueue);
  freeLoop = dropFarFree(freeLoop);
  if (free && isFreeStale(free, boat)) {
    free = null;
    changed = true;
  }

  // 4. Expire / replace the NOW card, then pop the next one.
  const nowTtl = nowTtlMs({ mode, playing });
  if (now && Number.isFinite(nowTtl) && nowMs - now.shownAt >= nowTtl) {
    now = null;
    changed = true;
  }
  if (now && playing && mode !== "suivre" && nowQueue.length && nowMs - now.shownAt >= TTL.nowReplaceMs) {
    // In playback the boat moves fast: a newer decision replaces the shown one.
    now = null;
    changed = true;
  }
  if (now && isStaleCard(now, { filmCum, mode })) {
    now = null;
    changed = true;
  }
  if (!now && nowQueue.length) {
    const sorted = sortNowQueue(nowQueue);
    now = { ...sorted[0], shownAt: nowMs };
    nowQueue = sorted.slice(1);
    changed = true;
  }

  // 5. FREE only breathes when nothing urgent is posted.
  if (!now) {
    const freeTtl = freeTtlMs({ mode, playing });
    if (free && Number.isFinite(freeTtl) && nowMs - free.shownAt >= freeTtl) {
      if (free.origin === "bag" && !freeLoop.some((c) => c.key === free.key)) freeLoop = [...freeLoop, free];
      free = null;
      changed = true;
    }
    if (!free && !freeQueue.length && freeLoop.length >= 2) {
      // Nothing new: loop on what is around the boat (bag cards only).
      freeQueue = freeLoop.map((c) => ({ ...c, loop: true }));
      freeLoop = [];
      changed = true;
    }
    if (!free && freeQueue.length) {
      free = { ...freeQueue[0], shownAt: nowMs };
      freeQueue = freeQueue.slice(1);
      changed = true;
    }
  }

  if (!changed) return prev || state;
  return { ...state, now, nowQueue, free, freeQueue, freeLoop, seen };
}

/** The visitor closes the NOW card: it never comes back; the next one shows. */
export function dismissNow(state, nowMs = Date.now()) {
  if (!state?.now) return state;
  const dismissed = new Set(state.dismissed);
  dismissed.add(state.now.key);
  const sorted = sortNowQueue(state.nowQueue);
  const next = sorted[0] ? { ...sorted[0], shownAt: nowMs } : null;
  return { ...state, now: next, nowQueue: sorted.slice(1), dismissed };
}

/** « Suivant » on the FREE block: the shown bag card joins the loop, the next one shows. */
export function nextFree(state, nowMs = Date.now()) {
  if (!state) return state;
  let freeLoop = state.freeLoop || [];
  if (state.free?.origin === "bag" && !freeLoop.some((c) => c.key === state.free.key)) {
    freeLoop = [...freeLoop, state.free];
  }
  let freeQueue = state.freeQueue;
  if (!freeQueue.length && freeLoop.length >= 2) {
    freeQueue = freeLoop.map((c) => ({ ...c, loop: true }));
    freeLoop = [];
  }
  const next = freeQueue[0] ? { ...freeQueue[0], shownAt: nowMs } : null;
  if (!next && !state.free) return state;
  return { ...state, free: next, freeQueue: freeQueue.slice(1), freeLoop };
}

/** Text read aloud for a card: title (info) + body. */
export function cardSpeech(card) {
  if (!card) return "";
  return [card.title, card.text].filter(Boolean).join(". ");
}
