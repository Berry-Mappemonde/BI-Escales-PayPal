/**
 * Le récit de la traversée — de Saint-Maur à la position d’aujourd’hui,
 * raconté dans l’ordre (revue du porteur, 19 sept. 2026) :
 *
 *   « L’expédition a quitté Saint-Maur le 15 mai… Le 15 mai, le bateau a pris
 *   la mer à La Rochelle vers Ajaccio : 1 820 nm en 9 jours ; vent moyen
 *   12 kn au bateau. Arrivée le 24 mai, 3 jours à quai. Puis départ le 27 mai
 *   vers Fort-de-France … Aujourd’hui … »
 *
 * Écrit à partir de ce qui est su : l’horloge officielle (dates d’escale,
 * jours à quai, milles), la position live, la jambe en cours, et le journal
 * de bord serveur (vent du GRIB au bateau, escales franchies, mots du
 * skipper) quand il est là. Zéro LLM, aucun chiffre inventé : quand une
 * donnée manque, la phrase manque.
 *
 * Retourne des paragraphes (FR / EN) ; le bouton « Écouter » les lit dans
 * l’ordre, la sidebar les affiche en Suivre.
 */

import { getCardinalDirection } from "../utils/getCardinalDirection.js";
import { isLandLegNames, nmToRoundedKm } from "../utils/berryLegs.js";
import { withoutForeignRegion } from "../utils/stopLabels.js";
import fr from "../i18n/fr.js";
import enDict from "../i18n/en.js";
import { cardFromJournalEntry } from "./momentCard.js";
import { originName, watersLabel } from "./toponyms.js";
import { DEFAULT_T0_ISO, rebaseIso, resolveStoryT0 } from "./voyageClock.js";

const MONTHS = {
  fr: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

function isEn(lang) {
  return String(lang || "").toLowerCase().startsWith("en");
}

function ms(iso) {
  const t = Date.parse(iso ?? "");
  return Number.isFinite(t) ? t : null;
}

/** "24 mai" / "24 May" ; with year when asked. */
export function dayMonth(iso, lang = "fr", { year = false } = {}) {
  const t = ms(iso);
  if (t == null) return "";
  const d = new Date(t);
  const m = MONTHS[isEn(lang) ? "en" : "fr"][d.getUTCMonth()];
  const day = d.getUTCDate();
  const y = year ? ` ${d.getUTCFullYear()}` : "";
  if (isEn(lang)) return `${day} ${m}${y}`;
  return `${day === 1 ? "1er" : day} ${m}${y}`;
}

function nmLabel(nm, lang) {
  const v = Math.round(Number(nm) || 0);
  return isEn(lang) ? `${v.toLocaleString("en-GB")} nm` : `${v.toLocaleString("fr-FR")} nm`;
}

/** Distance lue à voix haute : jamais « nm » (la synthèse dit « nanètres »). */
function spokenNmLabel(nm, lang) {
  const v = Math.round(Number(nm) || 0);
  if (isEn(lang)) return `${v.toLocaleString("en-GB")} nautical mile${v === 1 ? "" : "s"}`;
  return `${v.toLocaleString("fr-FR")} mille${v === 1 ? "" : "s"} nautique${v === 1 ? "" : "s"}`;
}

function isSaintMaur(name) {
  return /saint[\s-]*maur/i.test(String(name || ""));
}

/** Saint-Maur + 15 mai 2026 en tête. Les autres dates restent celles de la route. */
export function officialDatedStops(marks, clock) {
  const raw = marks?.length ? marks : (clock?.marks || []);
  const dated = datedMarks(raw);
  const saintRaw = (raw || []).find((m) => isSaintMaur(m?.name));
  const saint = dated.find((s) => isSaintMaur(s.name));
  const head = saint
    ? { ...saint, iso: DEFAULT_T0_ISO }
    : {
      name: saintRaw?.name || "Saint-Maur",
      iso: DEFAULT_T0_ISO,
      filmNm: Number(saintRaw?.filmNm ?? saintRaw?.nm) || 0,
      nm: Number.isFinite(Number(saintRaw?.nm)) ? Number(saintRaw.nm) : 0,
      holdHours: Number(saintRaw?.holdHours) || 0,
      lat: Number.isFinite(Number(saintRaw?.lat)) ? Number(saintRaw.lat) : null,
      lon: Number.isFinite(Number(saintRaw?.lon)) ? Number(saintRaw.lon) : null,
    };
  let rest = dated.filter((s) => !isSaintMaur(s.name));
  // Premier départ mer (La Rochelle, filmNm ~122) : 15 mai même sans iso,
  // et pas la date du retour (même nom, 2027).
  let sea = rest.find((s) => /rochelle/i.test(s.name || "")) || seaStop([], raw, clock);
  if (sea && /rochelle/i.test(sea.name || "")) {
    const film = Number(sea.filmNm ?? sea.nm) || 0;
    if (film < 2000) {
      const others = rest.filter((s) => !sameStop(s.name, sea.name));
      const nextMs = others[0] ? ms(others[0].iso) : null;
      const seaMs = ms(sea.iso);
      if (seaMs == null || (nextMs != null && seaMs >= nextMs)) {
        sea = { ...sea, iso: DEFAULT_T0_ISO };
      }
      rest = [sea, ...others];
    }
  }
  return [head, ...rest];
}

function seaStop(stops, marks, clock) {
  const fromStops = (stops || []).find((s, i) => i > 0 && /rochelle/i.test(s.name));
  if (fromStops) return fromStops;
  const raw = [...(marks || []), ...((clock?.marks) || [])];
  const lr = raw.find((m) => /rochelle/i.test(m?.name || ""));
  if (lr) {
    return {
      name: lr.name,
      iso: lr.iso,
      filmNm: Number(lr.filmNm ?? lr.nm) || 0,
      nm: Number.isFinite(Number(lr.nm)) ? Number(lr.nm) : 0,
      holdHours: Number(lr.holdHours) || 0,
      lat: Number.isFinite(Number(lr.lat)) ? Number(lr.lat) : null,
      lon: Number.isFinite(Number(lr.lon)) ? Number(lr.lon) : null,
    };
  }
  return stops?.[1] || { name: "La Rochelle" };
}

function units(lang) {
  return isEn(lang) ? enDict : fr;
}

function locNum(n, lang) {
  return Number(n).toLocaleString(isEn(lang) ? "en-GB" : "fr-FR");
}

function kmByRoadLabel(nm, lang) {
  const km = nmToRoundedKm(nm);
  if (km == null) return "";
  const u = units(lang);
  return `${locNum(km, lang)} ${u.unitKm} ${u.byRoad}`;
}

function roadHoursLabel(hours, lang) {
  const u = units(lang);
  return `${hours} ${u.unitRoadHours}`;
}

function isLandStep(from, to) {
  return isLandLegNames(from?.name, to?.name)
    || from?.vehicle === "land" || to?.vehicle === "land"
    || from?.kind === "land" || to?.kind === "land";
}

function hoursBetween(isoA, isoB) {
  const a = ms(isoA);
  const b = ms(isoB);
  if (a == null || b == null) return null;
  return Math.max(0, Math.round((b - a) / 3_600_000));
}

function days(hours) {
  return Math.max(0, Math.round((Number(hours) || 0) / 24));
}

function daysBetween(isoA, isoB) {
  const a = ms(isoA);
  const b = ms(isoB);
  if (a == null || b == null) return null;
  return Math.max(0, Math.round((b - a) / 86_400_000));
}

function joinList(parts, lang) {
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(", ")}${isEn(lang) ? " and " : " et "}${parts[parts.length - 1]}`;
}

function dayWord(n, lang) {
  if (isEn(lang)) return `${n} day${n > 1 ? "s" : ""}`;
  return `${n} jour${n > 1 ? "s" : ""}`;
}

function shortName(name) {
  // "Fort-de-France (Martinique)" stays; "Saint-Maur (Berry, Indre)" → "Saint-Maur".
  // "Açores (Corse)" perd le suffixe d'une autre escale.
  return withoutForeignRegion(name).replace(/\s*\(Berry, Indre\)\s*/, "").trim();
}

/** Same stopover: « Ajaccio » ≡ « Ajaccio (Corse) ». Berry does not call twice. */
export function normStop(name) {
  return String(name || "")
    .replace(/\s*\([^)]*\)\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function sameStop(a, b) {
  const na = normStop(a);
  const nb = normStop(b);
  return Boolean(na) && na === nb;
}

function compass(deg, lang) {
  const d = Number(deg);
  if (!Number.isFinite(d)) return "";
  const card = getCardinalDirection(d);
  return isEn(lang) ? card.replace(/O/g, "W") : card;
}

/** Stopovers with a date, in route order. Merge only sameStop (not filmNm). */
export function datedMarks(marks) {
  const out = [];
  for (const m of marks || []) {
    if (!m?.name || ms(m.iso) == null) continue;
    const film = Number(m.filmNm ?? m.nm) || 0;
    const key = normStop(m.name);
    if (!key) continue;
    // Même port (« Ajaccio » ≡ « Ajaccio (Corse) ») seulement.
    // Saint-Maur et La Rochelle restent distincts même à filmNm 0.
    if (out.some((x) => sameStop(x.name, m.name))) continue;
    out.push({
      name: m.name,
      iso: m.iso,
      filmNm: film,
      nm: Number.isFinite(Number(m.nm)) ? Number(m.nm) : film,
      holdHours: Number(m.holdHours) || 0,
      lat: Number.isFinite(Number(m.lat)) ? Number(m.lat) : null,
      lon: Number.isFinite(Number(m.lon)) ? Number(m.lon) : null,
    });
  }
  return out.sort((a, b) => a.filmNm - b.filmNm);
}

/** Departure from a stopover = arrival + days in port. */
function departureIso(stop) {
  const t = ms(stop?.iso);
  if (t == null) return null;
  return new Date(t + (Number(stop.holdHours) || 0) * 3_600_000).toISOString();
}

/** `events` = the whole voyage minus positions (server summary); `latest` = the recent tail. Deduped by id. */
function journalEntries(journal) {
  const all = [...(journal?.events || []), ...(journal?.latest || journal?.entries || [])];
  const seen = new Set();
  return all.filter((e) => {
    const id = e?.id || `${e?.kind}:${e?.t}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

/** GRIB entries of the journal between two instants: mean / max wind at the boat. */
function windBetween(journal, fromIso, toIso) {
  const a = ms(fromIso);
  const b = ms(toIso);
  if (a == null || b == null) return null;
  const winds = [];
  for (const e of journalEntries(journal)) {
    if (e?.kind !== "grib") continue;
    const t = ms(e.t);
    if (t == null || t < a || t > b) continue;
    const kn = Number(e.windKnots ?? e.wind?.windKnots);
    if (Number.isFinite(kn)) winds.push(kn);
  }
  if (!winds.length) return null;
  return {
    mean: Math.round(winds.reduce((s, x) => s + x, 0) / winds.length),
    max: Math.round(Math.max(...winds)),
    n: winds.length,
  };
}

/** Route events of the journal (v2: ZEE crossings, MPA within reach) between two instants, in order. */
function routeEventsBetween(journal, fromIso, toIso) {
  const a = ms(fromIso);
  const b = ms(toIso);
  if (a == null || b == null) return [];
  return journalEntries(journal)
    .filter((e) => ((e?.kind === "zee" || e?.kind === "amp" || e?.kind === "poe") && e.name) || e?.kind === "wx")
    .filter((e) => { const t = ms(e.t); return t != null && t >= a && t <= b; })
    .sort((x, y) => ms(x.t) - ms(y.t));
}

/** « Entre-temps : entrée dans la ZEE espagnole le 17 mai, haute mer le 20 mai ; AMP à portée : Pertuis Charentais. » */
function routeEventsSentence(events, lang) {
  if (!events.length) return "";
  const en = isEn(lang);
  // Entries only, each EEZ once (a re-entry after a short high-seas gap is not a new fact).
  const seenZee = new Set();
  const zee = events.filter((e) => {
    if (e.kind !== "zee" || e.event !== "enter") return false;
    const key = e.mrgid ?? e.name;
    if (seenZee.has(key)) return false;
    seenZee.add(key);
    return true;
  });
  const amp = events.filter((e) => e.kind === "amp");
  const bits = [];
  if (zee.length) {
    const parts = zee.slice(0, 6).map((e) => {
      const spoken = watersLabel(e.name, lang, { mrgid: Number.isInteger(e.mrgid) ? e.mrgid : null }) || e.name;
      return en ? `${spoken} on ${dayMonth(e.t, lang)}` : `${spoken} le ${dayMonth(e.t, lang)}`;
    });
    const more = zee.length > 6 ? (en ? ` and ${zee.length - 6} more` : ` et ${zee.length - 6} autres`) : "";
    bits.push(en ? `entered: ${parts.join(", ")}${more}` : `entré dans : ${parts.join(", ")}${more}`);
  }
  if (amp.length) {
    const names = amp.slice(0, 3).map((e) => originName(e.name) || e.name);
    const more = amp.length > 3 ? (en ? ` and ${amp.length - 3} more` : ` et ${amp.length - 3} autres`) : "";
    bits.push(en
      ? `marine protected area${amp.length > 1 ? "s" : ""} within reach: ${joinList(names, lang)}${more}`
      : `aire${amp.length > 1 ? "s" : ""} marine${amp.length > 1 ? "s" : ""} protégée${amp.length > 1 ? "s" : ""} à portée : ${joinList(names, lang)}${more}`);
  }
  // Ports of entry passed, each once.
  const seenPoe = new Set();
  const poe = events.filter((e) => {
    if (e.kind !== "poe") return false;
    const key = e.poeId ?? e.name;
    if (seenPoe.has(key)) return false;
    seenPoe.add(key);
    return true;
  });
  if (poe.length) {
    const names = poe.slice(0, 4).map((e) => originName(e.name) || e.name);
    const more = poe.length > 4 ? (en ? ` and ${poe.length - 4} more` : ` et ${poe.length - 4} autres`) : "";
    bits.push(en
      ? `port${poe.length > 1 ? "s" : ""} of entry passed: ${joinList(names, lang)}${more}`
      : `port${poe.length > 1 ? "s" : ""} d’entrée passé${poe.length > 1 ? "s" : ""} : ${joinList(names, lang)}${more}`);
  }
  const head = bits.length ? `${en ? "Meanwhile" : "Entre-temps"} — ${bits.join(" ; ")}.` : "";
  // Remarkable weather at the boat: derived from journaled GRIBs, cited with its numbers.
  const wx = events.filter((e) => e.kind === "wx" && Number.isFinite(Number(e.windKnots ?? e.hs)));
  let wxSentence = "";
  if (wx.length) {
    const parts = wx.slice(0, 3).map((e) => {
      const kn = Number.isFinite(e.windKnots) ? `${Math.round(e.windKnots)} kn` : "";
      const hs = Number.isFinite(e.hs) ? `Hs ${Number(e.hs).toLocaleString(en ? "en-GB" : "fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} m` : "";
      const what = e.event === "sea" ? (en ? "heavy sea" : "mer forte") : (en ? "gale" : "coup de vent");
      const nums = [kn, hs].filter(Boolean).join(", ");
      return `${what} ${en ? "on" : "le"} ${dayMonth(e.t, lang)}${nums ? ` (${nums})` : ""}`;
    });
    const more = wx.length > 3 ? (en ? ` and ${wx.length - 3} more` : ` et ${wx.length - 3} autres`) : "";
    wxSentence = en ? `Weather at the boat: ${joinList(parts, lang)}${more} (GFS).` : `Météo au bateau : ${joinList(parts, lang)}${more} (GFS).`;
  }
  return [head, wxSentence].filter(Boolean).join(" ");
}

/** Skipper notes of the journal between two instants (the human voice, verbatim). */
function notesBetween(journal, fromIso, toIso, max = 2) {
  const a = ms(fromIso);
  const b = ms(toIso);
  if (a == null || b == null) return [];
  return journalEntries(journal)
    .filter((e) => e?.kind === "note" && typeof e.text === "string" && e.text.trim())
    .filter((e) => { const t = ms(e.t); return t != null && t >= a && t <= b; })
    .slice(0, max)
    .map((e) => e.text.trim());
}

/** Latest GRIB entry of the journal (wind at the boat), if any. */
/** The most recent journaled GRIB — not later than `beforeMs` (a replay reads the past). */
function latestGrib(journal, beforeMs = null) {
  let best = null;
  for (const e of journalEntries(journal)) {
    if (e?.kind !== "grib") continue;
    const t = ms(e.t);
    if (beforeMs != null && t != null && t > beforeMs) continue;
    if (!best || t > ms(best.t)) best = e;
  }
  return best;
}

/** One passed leg, told in one paragraph: departure, crossing, arrival, port. */
function legParagraph(from, to, { journal, lang, sea, connector }) {
  const en = isEn(lang);
  const land = isLandStep(from, to);
  const dep = from === sea ? from.iso : departureIso(from);
  const sailNm = Math.max(0, (Number(to.nm) || 0) - (Number(from.nm) || 0));
  const filmNm = Math.max(0, (Number(to.filmNm) || 0) - (Number(from.filmNm) || 0));
  const legNm = land ? (filmNm || sailNm) : sailNm;
  const durDays = land ? null : daysBetween(dep, to.iso);
  const durHours = land ? hoursBetween(dep, to.iso) : null;
  const wind = land ? null : windBetween(journal, dep, to.iso);
  const notes = notesBetween(journal, dep, to.iso);
  const crossings = land ? "" : routeEventsSentence(routeEventsBetween(journal, dep, to.iso), lang);
  const bits = [];
  const conn = connector || storyConnector(0, lang);
  const head = from === sea
    ? (en
      ? `On ${dayMonth(dep, lang)}, the boat put to sea at ${shortName(from.name)}, bound for ${shortName(to.name)}`
      : `Le ${dayMonth(dep, lang)}, le bateau a pris la mer à ${shortName(from.name)}, vers ${shortName(to.name)}`)
    : (en
      ? `${conn}, on ${dayMonth(dep, lang)}, departure for ${shortName(to.name)}`
      : `${conn}, le ${dayMonth(dep, lang)}, départ vers ${shortName(to.name)}`);
  const facts = [];
  if (legNm > 0.5) facts.push(land ? kmByRoadLabel(legNm, lang) : nmLabel(legNm, lang));
  if (land && durHours != null && durHours > 0) {
    facts.push(en ? `in ${roadHoursLabel(durHours, lang)}` : `en ${roadHoursLabel(durHours, lang)}`);
  } else if (durDays != null && durDays > 0) {
    facts.push(en ? `in ${dayWord(durDays, lang)}` : `en ${dayWord(durDays, lang)}`);
  }
  bits.push(`${head}${facts.length ? ` : ${facts.join(" ")}` : ""}.`);
  if (crossings) bits.push(crossings);
  if (wind) {
    bits.push(en
      ? `Wind at the boat: ${wind.mean} kn on average, ${wind.max} kn at most (GFS, ${wind.n} readings).`
      : `Vent au bateau : ${wind.mean} kn en moyenne, ${wind.max} kn au plus fort (GFS, ${wind.n} relevés).`);
  }
  for (const n of notes) bits.push(en ? `The skipper wrote: « ${n} »` : `Le skipper a noté : « ${n} »`);
  const quay = days(to.holdHours);
  bits.push(en
    ? `Arrival at ${shortName(to.name)} on ${dayMonth(to.iso, lang)}${quay ? `, ${dayWord(quay, lang)} in port` : ""}.`
    : `Arrivée à ${shortName(to.name)} le ${dayMonth(to.iso, lang)}${quay ? `, ${dayWord(quay, lang)} à quai` : ""}.`);
  return bits.join(" ");
}

/**
 * @param {object} p
 * @param {object} p.clock      official clock (t0, marks[], vertices[])
 * @param {Array}  p.marks      legend marks (name, nm, filmNm, iso, holdHours)
 * @param {object} p.live       official live sample (filmNm, sailNm, iso, seaHours, atQuay, status, windKnots, dirFromDeg, kind, model)
 * @param {object} p.leg        hud leg (fromStop, toStop, remainingNm, etaHours, vehicle)
 * @param {object} p.journal    GET /voyage/official/journal payload (optional)
 * @param {Date|number|string} p.now
 * @param {string} p.lang
 * @returns {string[]} paragraphs, chronological
 */
export function expeditionStory({ clock, marks, live, leg, journal = null, now = Date.now(), lang = "fr", t0: storyT0 } = {}) {
  const en = isEn(lang);
  const nowMs = now instanceof Date ? now.getTime() : (typeof now === "number" ? now : ms(now));
  const rawMarks = marks?.length ? marks : clock?.marks;
  if (!rawMarks?.length && !clock?.t0) return [];
  const t0 = ms(DEFAULT_T0_ISO);
  const stops = officialDatedStops(rawMarks, clock);
  if (t0 == null && !stops.length) return [];
  const out = [];

  const start = stops[0];
  const sea = seaStop(stops, marks, clock);
  const departIso = resolveStoryT0(storyT0);

  // 1. Le départ.
  if (nowMs != null && t0 != null && nowMs < t0) {
    out.push(en
      ? `The Berry-Mappemonde expedition leaves ${shortName(start?.name || "Saint-Maur")} on ${dayMonth(departIso, lang, { year: true })}${sea ? ` and puts to sea at ${shortName(sea.name)}` : ""}.`
      : `L’expédition Berry-Mappemonde quitte ${shortName(start?.name || "Saint-Maur")} le ${dayMonth(departIso, lang, { year: true })}${sea ? ` et prend la mer à ${shortName(sea.name)}` : ""}.`);
    return out;
  }
  out.push(en
    ? `The Berry-Mappemonde expedition left ${shortName(start?.name || "Saint-Maur")} on ${dayMonth(departIso, lang, { year: true })}.`
    : `L’expédition Berry-Mappemonde a quitté ${shortName(start?.name || "Saint-Maur")} le ${dayMonth(departIso, lang, { year: true })}.`);

  // 2. Chaque jambe franchie, dans l’ordre : départ, traversée, arrivée, quai.
  // L’étape terrestre Saint-Maur → La Rochelle est incluse (km, pas nm).
  const boatFilm = Number(live?.filmNm);
  const passed = [];
  for (let i = 0; i < stops.length - 1; i++) {
    const from = stops[i];
    const to = stops[i + 1];
    if (nowMs != null && ms(to.iso) > nowMs) break;
    if (Number.isFinite(boatFilm) && to.filmNm > boatFilm + 0.6) break;
    passed.push([from, to]);
  }
  let connI = 0;
  for (const [from, to] of passed) {
    const needsConn = from !== sea;
    const connector = storyConnector(connI, lang);
    if (needsConn) connI += 1;
    out.push(legParagraph(from, to, { journal, lang, sea, connector }));
  }

  // 3. La jambe en cours, puis aujourd’hui.
  if (live && Number.isFinite(boatFilm)) {
    const current = passed.length ? passed[passed.length - 1][1] : sea;
    const to = leg?.toStop ? shortName(leg.toStop) : null;
    const nextMark = to ? stops.find((s) => s.name === leg.toStop) : null;
    const eta = nextMark ? dayMonth(nextMark.iso, lang) : null;
    const left = Number(leg?.remainingNm);
    const dayAtSea = days(live.seaHours);
    const elapsed = t0 != null && nowMs != null ? Math.max(0, Math.floor((nowMs - t0) / 86_400_000)) : null;
    // In a replay the "today" of the story is the replayed day.
    const todayWord = live.replay ? (en ? "That day" : "Ce jour-là") : (en ? "Today" : "Aujourd’hui");
    const when = elapsed != null
      ? (en ? `${todayWord}, day ${elapsed}${dayAtSea ? ` (${dayAtSea} at sea)` : ""}` : `${todayWord}, jour ${elapsed}${dayAtSea ? ` (${dayAtSea} de mer)` : ""}`)
      : todayWord;
    const dist = nmLabel(live.sailNm ?? live.filmNm, lang);

    if (live.status === "arrived") {
      out.push(en
        ? `${when}: the boat has arrived — ${dist} logged since the start.`
        : `${when} : le bateau est arrivé — ${dist} parcourus depuis le départ.`);
    } else if (live.atQuay && leg?.fromStop) {
      const here = shortName(leg.fromStop);
      out.push(en
        ? `${when}: the boat is in port at ${here}, ${dist} from the start${to ? `; next leg to ${to}${eta ? `, expected on ${eta}` : ""}` : ""}.`
        : `${when} : le bateau est à quai à ${here}, à ${dist} du départ${to ? ` ; prochaine jambe vers ${to}${eta ? `, arrivée prévue le ${eta}` : ""}` : ""}.`);
    } else if (live.vehicle === "plane") {
      out.push(en
        ? `${when}: the crew is in the air${to ? `, heading for ${to}` : ""} — the boat stays where it is.`
        : `${when} : l’équipage est dans les airs${to ? `, vers ${to}` : ""} — le bateau ne bouge pas.`);
    } else {
      const dep = current && current !== sea ? departureIso(current) : current?.iso;
      const since = current && dep
        ? (en
          ? `Since ${dayMonth(dep, lang)}, under way from ${shortName(current.name)}${to ? ` to ${to}` : ""}`
          : `Depuis le ${dayMonth(dep, lang)}, en route de ${shortName(current.name)}${to ? ` vers ${to}` : ""}`)
        : (en ? `Under way${to ? ` to ${to}` : ""}` : `En route${to ? ` vers ${to}` : ""}`);
      const untilIso = live.iso || new Date(nowMs).toISOString();
      const wind = current && dep ? windBetween(journal, dep, untilIso) : null;
      const crossings = current && dep ? routeEventsSentence(routeEventsBetween(journal, dep, untilIso), lang) : "";
      const tail = [
        Number.isFinite(left) && left > 0.5 ? (en ? `${nmLabel(left, lang)} to go` : `encore ${nmLabel(left, lang)}`) : null,
        eta ? (en ? `expected on ${eta}` : `arrivée prévue le ${eta}`) : null,
      ].filter(Boolean).join(", ");
      out.push(`${since}${tail ? ` : ${tail}` : ""}.${crossings ? ` ${crossings}` : ""}${wind ? (en
        ? ` Wind at the boat so far: ${wind.mean} kn on average, ${wind.max} kn at most (GFS).`
        : ` Vent au bateau depuis : ${wind.mean} kn en moyenne, ${wind.max} kn au plus fort (GFS).`) : ""}`);
      out.push(en
        ? `${when}: the boat is ${dist} from the start.`
        : `${when} : le bateau est à ${dist} du départ.`);
    }
  }

  // 4. Le vent au bateau maintenant (GRIB live, sinon dernière entrée du journal).
  const wind = live?.kind === "forecast" && Number.isFinite(live.windKnots)
    ? { kn: live.windKnots, from: live.dirFromDeg, model: live.model, when: null }
    : null;
  const g = !wind ? latestGrib(journal, nowMs) : null;
  const gw = g && Number.isFinite(g.windKnots ?? g.wind?.windKnots)
    ? { kn: g.windKnots ?? g.wind.windKnots, from: g.dirFromDeg ?? g.wind?.dirFromDeg, model: g.model || g.wind?.model, when: g.t }
    : null;
  const w = wind || gw;
  if (w) {
    const from = compass(w.from, lang);
    const kn = Math.round(Number(w.kn));
    out.push(en
      ? `${w.when ? `On ${dayMonth(w.when, lang)}, at the boat` : "At the boat now"}: wind ${kn} kn${from ? ` from the ${from}` : ""}${w.model ? ` (${w.model} forecast)` : ""}.`
      : `${w.when ? `Le ${dayMonth(w.when, lang)}, au bateau` : "Au bateau maintenant"} : vent ${kn} kn${from ? ` de ${from}` : ""}${w.model ? ` (prévision ${w.model})` : ""}.`);
  }

  return out;
}

export function expeditionStoryText(params) {
  return expeditionStory(params).join("\n\n");
}

/** Script brut du film (règles), bilingue, ≤ 2 400 caractères. */
export const FILM_MAX_CHARS = 2400;
export const FILM_MIN_EVENTS = 6;
export const FILM_MAX_EVENTS = 9;
export const FILM_GAP_FRAC = 0.03;
export const FILM_KIND_RANK = Object.freeze({
  wx: 0, climo: 1, sci: 2, amp: 3, zee: 4, poe: 5, note: 6, stop: 7,
});
export const FILM_CONNECTORS = Object.freeze({
  fr: ["Puis", "Ensuite", "Plus loin", "De là", "Sur la route", "À la jambe suivante"],
  en: ["Then", "Next", "Further on", "From there", "On the way", "On the next leg"],
});

/** Connecteur du paragraphe i : `connecteurs[i % n]` (jamais le même à la suite, n > 1). */
export function storyConnector(i, lang = "fr") {
  const list = FILM_CONNECTORS[isEn(lang) ? "en" : "fr"];
  return list[Math.abs(Number(i) || 0) % list.length];
}

const SCORED_KINDS = new Set(["wx", "climo", "sci", "amp", "zee", "poe", "note"]);
const CANDIDATE_KINDS = new Set(["stop", "zee", "amp", "poe", "wx", "climo", "sci", "note"]);

function isoOf(msOrIso) {
  if (msOrIso == null) return null;
  if (typeof msOrIso === "string") return Number.isFinite(ms(msOrIso)) ? new Date(ms(msOrIso)).toISOString() : null;
  if (typeof msOrIso === "number" && Number.isFinite(msOrIso)) return new Date(msOrIso).toISOString();
  return null;
}

function numPlain(v, digits = 0) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  const f = digits > 0 ? n.toFixed(digits) : String(Math.round(n));
  return f.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function quayDaysOf(entry) {
  if (Number.isFinite(Number(entry?.daysAtQuay))) return Number(entry.daysAtQuay);
  if (Number.isFinite(Number(entry?.holdHours))) return days(entry.holdHours);
  return 0;
}

function factNum(entry, ...keys) {
  for (const k of keys) {
    const v = entry?.[k] ?? entry?.facts?.[k];
    if (Number.isFinite(Number(v))) return Number(v);
  }
  return null;
}

/** Score déterministe : wx = max × durée ; sinon rang du kind. */
export function scoreFilmEvent(entry) {
  const kind = entry?.kind;
  if (kind === "wx") {
    const peak = factNum(entry, "maxWindKnots", "windKnots") || 0;
    const dur = factNum(entry, "hours") || 6;
    return peak * dur;
  }
  if (kind === "climo") return 50;
  if (kind === "sci") return 40;
  if (kind === "amp") return 30;
  if (kind === "zee") return 20;
  if (kind === "poe") return 10;
  if (kind === "note") return 5;
  if (kind === "stop") return 1;
  return 0;
}

function candidateId(entry, fallback) {
  return String(entry?.id || fallback || `${entry?.kind}:${entry?.t || ""}`);
}

function toCandidate(entry, extras = {}) {
  const tMs = ms(entry?.t);
  if (tMs == null) return null;
  const id = candidateId(entry, extras.id);
  return {
    id,
    kind: entry.kind,
    t: entry.t,
    tMs,
    name: entry.name || extras.name || "",
    score: extras.score != null ? extras.score : scoreFilmEvent(entry),
    role: extras.role || null,
    quayDays: extras.quayDays != null ? extras.quayDays : quayDaysOf(entry),
    entry,
  };
}

/**
 * Candidats du journal (stop, zee, amp, poe, wx, climo, sci, note)
 * + départ / aujourd'hui si absents.
 */
function marksWithIso(marks, clock) {
  const raw = marks?.length ? marks : (clock?.marks || []);
  const clockMarks = clock?.marks || [];
  return (raw || []).map((m) => {
    if (m?.iso) return m;
    const film = Number(m?.filmNm ?? m?.nm);
    const hit = clockMarks.find((c) => (
      Number.isFinite(film) && Math.abs((c.filmNm ?? c.nm) - film) < 0.6 && (!m?.name || c.name === m.name)
    )) || clockMarks.find((c) => m?.name && c.name === m.name);
    return hit ? { ...m, iso: hit.iso, holdHours: hit.holdHours ?? m.holdHours, lat: m.lat ?? hit.lat, lon: m.lon ?? hit.lon } : m;
  });
}

export function filmCandidates({ journal, marks, clock, live, now = Date.now() } = {}) {
  const stops = officialDatedStops(marksWithIso(marks, clock), clock);
  const start = stops[0];
  const sea = seaStop(stops, marks, clock);
  const t0 = ms(DEFAULT_T0_ISO);
  const nowMs = now instanceof Date ? now.getTime() : (typeof now === "number" ? now : ms(now));
  const tEnd = ms(live?.iso) || nowMs;
  const out = [];
  const seen = new Set();

  const push = (c) => {
    if (!c || !c.id || seen.has(c.id)) return;
    seen.add(c.id);
    out.push(c);
  };

  const departIso = DEFAULT_T0_ISO;
  if (ms(departIso) != null) {
    push(toCandidate({
      id: "depart",
      kind: "stop",
      t: departIso,
      event: "departure",
      name: shortName(start?.name || "Saint-Maur"),
    }, { role: "depart", score: 10_000, name: shortName(start?.name || "Saint-Maur") }));
  }

  const seenZee = new Set();
  const seenPoe = new Set();
  const seenSci = new Set();
  for (const e of journalEntries(journal)) {
    if (!CANDIDATE_KINDS.has(e?.kind)) continue;
    if (e.kind === "zee") {
      if (e.event && e.event !== "enter") continue;
      const key = e.mrgid ?? e.name;
      if (!key || seenZee.has(key)) continue;
      seenZee.add(key);
    }
    if (e.kind === "poe") {
      const key = e.poeId ?? e.name;
      if (!key || seenPoe.has(key)) continue;
      seenPoe.add(key);
    }
    if (e.kind === "sci") {
      const key = e.entity?.id ?? e.name;
      if (!key || seenSci.has(key)) continue;
      seenSci.add(key);
    }
    if (e.kind === "stop" && e.event === "departure") continue;
    const t = ms(e.t);
    if (t == null) continue;
    if (t0 != null && t < t0) continue;
    if (tEnd != null && t > tEnd) continue;
    push(toCandidate(e, { role: e.kind === "stop" ? "stop" : null }));
  }

  // Escales de l'horloge si le journal n'en a pas encore.
  for (const s of stops.slice(1)) {
    const t = ms(s.iso);
    if (t == null || (tEnd != null && t > tEnd)) continue;
    const id = `stop:${s.name}:${s.iso}`;
    if (out.some((c) => c.kind === "stop" && c.role !== "depart" && c.role !== "today" && sameStop(c.name, s.name) && Math.abs(c.tMs - t) < 3_600_000)) {
      continue;
    }
    push(toCandidate({
      id,
      kind: "stop",
      t: s.iso,
      event: "arrival",
      name: s.name,
      holdHours: s.holdHours,
      daysAtQuay: days(s.holdHours),
    }, { role: "stop", score: 1 }));
  }

  const todayIso = live?.iso || (tEnd != null ? new Date(tEnd).toISOString() : isoOf(nowMs));
  if (todayIso) {
    push(toCandidate({
      id: "today",
      kind: "stop",
      t: todayIso,
      event: "arrival",
      name: live?.atQuay && live?.fromStop ? shortName(live.fromStop) : "",
    }, { role: "today", score: 9_000 }));
  }

  return { candidates: out.sort((a, b) => a.tMs - b.tMs), t0, tEnd, start, sea, stops };
}

function pickStops(stops, max = 6) {
  const list = stops.filter((c) => c.kind === "stop" && c.role !== "depart" && c.role !== "today");
  if (list.length <= max) return list;
  const first = list[0];
  const last = list[list.length - 1];
  const long = list.filter((s) => s.quayDays > 2 && s !== first && s !== last)
    .sort((a, b) => b.quayDays - a.quayDays || a.tMs - b.tMs);
  const picked = [];
  const add = (s) => {
    if (s && !picked.some((x) => x.id === s.id)) picked.push(s);
  };
  add(first);
  add(last);
  for (const s of long) {
    if (picked.length >= max) break;
    add(s);
  }
  if (picked.length < max) {
    for (const s of list) {
      if (picked.length >= max) break;
      add(s);
    }
  }
  return picked.sort((a, b) => a.tMs - b.tMs).slice(0, max);
}

/**
 * Départ, escales (max 6), aujourd'hui, puis wx > climo > sci > amp > zee > poe
 * jusqu'à 6–9, jamais deux à moins de 3 % du temps total.
 */
export function selectFilmEvents(candidates, { t0, tEnd } = {}) {
  const list = (candidates || []).filter((c) => c && c.tMs != null);
  const span = (Number(tEnd) || 0) - (Number(t0) || 0);
  const gap = span > 0 ? span * FILM_GAP_FRAC : 0;
  const depart = list.find((c) => c.role === "depart" || c.id === "depart");
  const today = list.find((c) => c.role === "today" || c.id === "today");
  const must = [];
  if (depart) must.push(depart);
  must.push(...pickStops(list, 6));
  if (today) must.push(today);
  const selected = [...must];
  const tooClose = (ev) => gap > 0 && selected.some((s) => Math.abs(s.tMs - ev.tMs) < gap);
  const scored = list
    .filter((c) => SCORED_KINDS.has(c.kind) && !must.some((m) => m.id === c.id))
    .sort((a, b) => {
      const ds = (b.score || 0) - (a.score || 0);
      if (ds) return ds;
      const dr = (FILM_KIND_RANK[a.kind] ?? 9) - (FILM_KIND_RANK[b.kind] ?? 9);
      if (dr) return dr;
      return a.tMs - b.tMs;
    });
  for (const ev of scored) {
    if (selected.length >= FILM_MAX_EVENTS) break;
    if (tooClose(ev)) continue;
    selected.push(ev);
  }
  if (selected.length < FILM_MIN_EVENTS) {
    for (const ev of scored) {
      if (selected.length >= FILM_MIN_EVENTS) break;
      if (selected.some((s) => s.id === ev.id)) continue;
      selected.push(ev);
    }
  }
  return selected.sort((a, b) => a.tMs - b.tMs);
}

function placeOf(entry, lang) {
  const name = entry?.place || (entry?.name && entry.kind !== "wx" && entry.kind !== "stop" ? entry.name : "");
  if (!name) return "";
  return isEn(lang) ? ` off ${name}` : ` au large de ${name}`;
}

/** Phrase d'événement depuis un gabarit — uniquement des faits déjà là. */
export function filmEventSentence(ev, lang = "fr") {
  const en = isEn(lang);
  const e = ev?.entry || ev;
  const when = dayMonth(e.t || ev.t, lang);
  const rawName = e.name || ev.name || "";
  const kind = e.kind || ev.kind;
  const name = kind === "zee"
    ? (watersLabel(rawName, lang, { mrgid: Number.isInteger(e.mrgid) ? e.mrgid : Number.isInteger(ev.mrgid) ? ev.mrgid : null }) || shortName(rawName))
    : originName(shortName(rawName));
  if (ev.role === "depart") {
    const sea = shortName(ev.seaName || ev.toName || "");
    const from = name || "Saint-Maur";
    const when = dayMonth(e.t, lang, { year: true });
    if (sea) {
      return en
        ? `The Berry-Mappemonde expedition left ${from} on ${when} and took the road to ${sea}.`
        : `L’expédition Berry-Mappemonde a quitté ${from} le ${when} et a pris la route vers ${sea}.`;
    }
    return en
      ? `The Berry-Mappemonde expedition left ${from} on ${when}.`
      : `L’expédition Berry-Mappemonde a quitté ${from} le ${when}.`;
  }
  if (ev.role === "today") {
    const nm = ev.distLabel || "";
    const head = en ? "Today" : "Aujourd’hui";
    return nm
      ? (en ? `${head}, the boat is ${nm} from the start.` : `${head}, le bateau est à ${nm} du départ.`)
      : (en ? `${head}, the boat is at its position of the moment.` : `${head}, le bateau est à sa position du moment.`);
  }
  if (ev.kind === "stop") {
    const quay = quayDaysOf(e);
    const sights = (Array.isArray(e.sights) ? e.sights : e.facts?.sights || []).slice(0, 2)
      .map((s) => (typeof s === "string" ? s : s?.name)).filter(Boolean);
    const extra = sights.length ? ` ${joinList(sights, lang)}.` : "";
    return en
      ? `Stopover in ${name} on ${when}${quay ? `, ${dayWord(quay, lang)} in port` : ""}.${extra}`
      : `Escale à ${name} le ${when}${quay ? `, ${dayWord(quay, lang)} à quai` : ""}.${extra}`;
  }
  if (ev.kind === "wx") {
    const kn = numPlain(factNum(e, "maxWindKnots", "windKnots"));
    const hours = factNum(e, "hours");
    const hs = factNum(e, "hs", "maxHs");
    const dur = hours != null ? (en ? ` for ${numPlain(hours)} hours` : ` pendant ${numPlain(hours)} heures`) : "";
    const sea = hs != null ? (en ? `, Hs ${numPlain(hs, 1)} m` : `, Hs ${numPlain(hs, 1)} m`) : "";
    const place = placeOf(e, lang);
    return en
      ? `On ${when}${place}, the wind rose to ${kn} kn${dur}${sea}.`
      : `Le ${when}${place}, le vent est monté à ${kn} kn${dur}${sea}.`;
  }
  if (ev.kind === "climo") {
    const event = e.event || "";
    const detail = event === "calms"
      ? (en ? " — equatorial calms" : " — calmes équatoriaux")
      : event === "cyclone-enter"
        ? (en ? " — cyclone season" : " — saison cyclonique")
        : (en ? " — wind regime" : " — régime de vent");
    const deg = factNum(e, "deltaDeg");
    const degBit = deg != null ? (en ? ` (${numPlain(deg)}°)` : ` (${numPlain(deg)}°)`) : "";
    return en
      ? `On ${when}, the climate regime changed${detail}${degBit}.`
      : `Le ${when}, le régime climatique a changé${detail}${degBit}.`;
  }
  if (ev.kind === "sci") {
    const nm = factNum(e, "nm");
    const nmBit = nm != null
      ? (en ? ` at ${numPlain(nm, 1)} nautical miles` : ` à ${numPlain(nm, 1)} milles nautiques`)
      : "";
    return en
      ? `On ${when}, the route passed${nmBit} from ${name}.`
      : `Le ${when}, la route est passée${nmBit} de ${name}.`;
  }
  if (ev.kind === "amp") {
    return en
      ? `On ${when}, marine protected area within reach: ${name}.`
      : `Le ${when}, aire marine protégée à portée : ${name}.`;
  }
  if (ev.kind === "zee") {
    return en
      ? `On ${when}, entered ${name}.`
      : `Le ${when}, entrée dans ${name}.`;
  }
  if (ev.kind === "poe") {
    return en
      ? `On ${when}, port of entry passed: ${name}.`
      : `Le ${when}, port d’entrée passé : ${name}.`;
  }
  if (ev.kind === "note" && e.text) {
    const note = String(e.text).trim().slice(0, 120);
    return en
      ? `On ${when}, the skipper wrote: « ${note} »`
      : `Le ${when}, le skipper a noté : « ${note} »`;
  }
  return "";
}

function legIntro(from, to, connector, lang, { first, sea, storyT0 = DEFAULT_T0_ISO }) {
  const en = isEn(lang);
  const rawDep = first ? from?.iso : departureIso(from) || from?.iso;
  const depIso = rebaseIso(rawDep, DEFAULT_T0_ISO, storyT0);
  const dest = shortName(to?.name || "");
  const origin = shortName(from?.name || "");
  if (first) {
    return "";
  }
  const head = dest
    ? (en ? `departure for ${dest}` : `départ vers ${dest}`)
    : (en ? `under way from ${origin}` : `en route depuis ${origin}`);
  return en
    ? `${connector}, on ${dayMonth(depIso, lang)}, ${head}.`
    : `${connector}, le ${dayMonth(depIso, lang)}, ${head}.`;
}

/** Phrase de départ de CETTE fenêtre : dest de la jambe, jamais un seaName figé. */
function chapterDepart(w, i, lang, storyT0 = DEFAULT_T0_ISO) {
  const dest = w.to && w.to.name ? w.to : null;
  const destName = shortName(dest?.name || "");
  const origin = shortName(w.from?.name || "");
  const en = isEn(lang);
  const head = destName
    ? (en ? `departure for ${destName}` : `départ vers ${destName}`)
    : (en ? `under way from ${origin}` : `en route depuis ${origin}`);
  if (i === 0) {
    if (!destName) return "";
    return `${head[0].toUpperCase()}${head.slice(1)}.`;
  }
  return legIntro(w.from, dest, storyConnector(i - 1, lang), lang, { first: false, storyT0 });
}

function chapterWindows(stops, t0, tEnd) {
  const list = [];
  const pts = stops.length ? stops : [{ name: "Saint-Maur", iso: isoOf(t0), filmNm: 0 }];
  for (let i = 0; i < pts.length; i++) {
    const from = pts[i];
    const to = pts[i + 1];
    const tA = ms(from.iso) ?? (i === 0 ? t0 : null);
    if (tA == null || (tEnd != null && tA >= tEnd)) break;
    const destMs = to ? ms(to.iso) : null;
    const arrived = destMs != null && destMs <= tEnd;
    const rawB = destMs != null ? destMs : tEnd;
    let tB = Math.min(rawB == null ? tEnd : rawB, tEnd);
    if (tB <= tA) tB = tA + 1000;
    list.push({
      id: `leg-${i}`,
      from,
      to: arrived ? to : null,
      tA,
      tB,
      fromName: from.name || "",
      toName: arrived ? (to.name || "") : "",
      fromLat: Number.isFinite(from.lat) ? from.lat : null,
      fromLon: Number.isFinite(from.lon) ? from.lon : null,
      toLat: Number.isFinite(to?.lat) ? to.lat : null,
      toLon: Number.isFinite(to?.lon) ? to.lon : null,
    });
    if (!to || (destMs != null && destMs >= tEnd)) break;
  }
  if (!list.length && t0 != null && tEnd != null && tEnd > t0) {
    list.push({
      id: "leg-0",
      from: pts[0],
      to: null,
      tA: t0,
      tB: tEnd,
      fromName: pts[0]?.name || "Saint-Maur",
      toName: "",
      fromLat: null,
      fromLon: null,
      toLat: null,
      toLon: null,
    });
  }
  return list;
}

function windowOwnsEvent(w, ev, i) {
  if (ev?.kind === "stop" && ev.role !== "depart" && ev.role !== "today" && w.toName && sameStop(w.toName, ev.name)) {
    return true;
  }
  // Arrival at tB belongs to this jambe (]tA, tB]), not the next « départ vers ».
  if (i === 0) return ev.tMs >= w.tA && ev.tMs <= w.tB;
  return ev.tMs > w.tA && ev.tMs <= w.tB;
}

function assignToChapters(events, windows) {
  const buckets = windows.map(() => []);
  for (const ev of events) {
    let idx = windows.findIndex((w, i) => windowOwnsEvent(w, ev, i));
    if (idx < 0) idx = ev.role === "today" ? windows.length - 1 : 0;
    if (idx >= 0) buckets[idx].push(ev);
  }
  return buckets;
}

function arrivalSentence(to, lang, storyT0 = DEFAULT_T0_ISO) {
  if (!to?.name || ms(to.iso) == null) return "";
  const en = isEn(lang);
  const quay = days(to.holdHours);
  const when = dayMonth(rebaseIso(to.iso, DEFAULT_T0_ISO, storyT0), lang);
  return en
    ? `Arrival at ${shortName(to.name)} on ${when}${quay ? `, ${dayWord(quay, lang)} in port` : ""}.`
    : `Arrivée à ${shortName(to.name)} le ${when}${quay ? `, ${dayWord(quay, lang)} à quai` : ""}.`;
}

function composeChapters(windows, buckets, { lang, seaName, startName, live, storyT0 = DEFAULT_T0_ISO }) {
  const chapters = [];
  const cited = new Set();
  const pushArrival = (bits, dest) => {
    const key = dest ? normStop(dest.name) : "";
    const sentence = dest ? arrivalSentence(dest, lang, storyT0) : "";
    if (!sentence || !key || cited.has(key)) return;
    bits.push(sentence);
    cited.add(key);
  };
  for (let i = 0; i < windows.length; i++) {
    const w = windows[i];
    const bits = [];
    const placed = [];
    const dest = w.to && w.to.name ? w.to : null;
    const destName = dest ? shortName(dest.name) : "";
    if (i === 0) {
      const left = filmEventSentence({
        role: "depart",
        kind: "stop",
        t: storyT0,
        name: startName,
        seaName: destName ? "" : seaName,
        entry: { t: storyT0, name: startName },
      }, lang).trim();
      if (left) bits.push(left);
    }
    const head = chapterDepart(w, i, lang, storyT0);
    if (head) bits.push(head);
    pushArrival(bits, dest);
    for (const ev of buckets[i] || []) {
      // Stopovers are the jambe destination, already paired above — not a second cite.
      if (ev.kind === "stop" && ev.role !== "depart" && ev.role !== "today") continue;
      if (ev.role === "depart") continue;
      const displayT = rebaseIso(ev.t || ev.entry?.t, DEFAULT_T0_ISO, storyT0);
      const rich = {
        ...ev,
        t: displayT,
        seaName: destName || seaName,
        toName: destName,
        distLabel: live ? spokenNmLabel(live.sailNm ?? live.filmNm, lang) : "",
        entry: ev.entry ? { ...ev.entry, t: rebaseIso(ev.entry.t, DEFAULT_T0_ISO, storyT0) } : ev.entry,
      };
      const sentence = filmEventSentence(rich, lang).trim();
      if (!sentence) continue;
      const charIdx = bits.join(" ").length + (bits.length ? 1 : 0);
      bits.push(sentence);
      const card = cardFromJournalEntry(ev.entry, lang);
      placed.push({ id: ev.id, charIdx, card: card || { id: ev.id, kind: ev.kind, title: ev.name || ev.kind, text: sentence } });
    }
    const text = bits.join(" ").replace(/\s{2,}/g, " ").trim();
    chapters.push({
      id: w.id,
      tA: isoOf(w.tA),
      tB: isoOf(w.tB),
      text,
      events: placed,
      fromName: w.fromName,
      toName: w.toName,
      fromLat: w.fromLat,
      fromLon: w.fromLon,
      toLat: w.toLat,
      toLon: w.toLon,
    });
  }
  return chapters;
}

function scriptChars(chapters) {
  return chapters.reduce((s, c) => s + String(c.text || "").length, 0);
}

/**
 * Script brut : chapitres = jambes, connecteurs en rotation, gabarits,
 * longueur ≤ 2 400 (on retire d'abord les événements de score le plus bas).
 */
export function buildFilmScript({
  clock, marks, live, journal = null, now = Date.now(), lang = "fr", seconds = 150, t0: storyT0,
} = {}) {
  const packed = filmCandidates({ journal, marks, clock, live, now });
  const { t0, tEnd, start, sea, stops } = packed;
  if (t0 == null || tEnd == null || !(tEnd > t0)) {
    return { chapters: [], source: "rules", chars: 0, targetSeconds: seconds };
  }
  const displayT0 = resolveStoryT0(storyT0);
  const startName = shortName(start?.name || "Saint-Maur");
  const seaName = shortName(sea?.name || "La Rochelle");
  const selected = selectFilmEvents(packed.candidates, { t0, tEnd }).map((ev) => (
    ev.role === "depart" ? { ...ev, seaName, name: startName } : ev
  ));
  const mustIds = new Set(selected.filter((e) => e.role === "depart" || e.role === "today" || e.role === "stop").map((e) => e.id));
  const windows = chapterWindows(stops, t0, tEnd);
  const compose = (events) => composeChapters(windows, assignToChapters(events, windows), {
    lang, seaName, startName, live, storyT0: displayT0,
  });
  let events = selected;
  let chapters = compose(events);
  while (scriptChars(chapters) > FILM_MAX_CHARS) {
    const droppable = events.filter((e) => !mustIds.has(e.id));
    if (!droppable.length) break;
    droppable.sort((a, b) => (a.score || 0) - (b.score || 0) || b.tMs - a.tMs);
    const drop = droppable[0];
    events = events.filter((e) => e.id !== drop.id);
    chapters = compose(events);
  }
  const chars = scriptChars(chapters);
  return { chapters, source: "rules", chars, targetSeconds: Number(seconds) || 150 };
}
