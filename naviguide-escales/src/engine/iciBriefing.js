/**
 * Story of the `ici()` bag — one briefing, not four agents.
 * Tells only what is around the boat.
 */

import { briefingEntities, placeLabel, segmentBriefingWithSources } from "./briefingLinks.js";
import enDict from "../i18n/en.js";
import frDict from "../i18n/fr.js";
import { trafficKind } from "./ampRules.js";
import { originName, spokenZeeName, watersLabel } from "./toponyms.js";
import { getCardinalDirection } from "../utils/getCardinalDirection.js";
import { haversineNm } from "../utils/geo.js";
import { localizePlaceName } from "../utils/placeNames.js";
import { filmZeeBucket, filmZeeForBucket } from "./filmZeeStep.js";
import { displayStopName } from "../utils/stopLabels.js";

const TERRITORY = {
  fr: {
    france_metropolitaine: "France métropolitaine",
    guyane: "Guyane",
    martinique: "Martinique",
    guadeloupe: "Guadeloupe",
    saint_barthelemy: "Saint-Barthélemy",
    saint_martin: "Saint-Martin (partie française)",
    saint_pierre_et_miquelon: "Saint-Pierre-et-Miquelon",
    polynesie_francaise: "Polynésie française",
    nouvelle_caledonie: "Nouvelle-Calédonie",
    wallis_et_futuna: "Wallis-et-Futuna",
    la_reunion: "La Réunion",
    mayotte: "Mayotte",
    taaf: "Terres australes et antarctiques françaises",
  },
  en: {
    france_metropolitaine: "metropolitan France",
    guyane: "French Guiana",
    martinique: "Martinique",
    guadeloupe: "Guadeloupe",
    saint_barthelemy: "Saint Barthélemy",
    saint_martin: "Saint-Martin (French side)",
    saint_pierre_et_miquelon: "Saint Pierre and Miquelon",
    polynesie_francaise: "French Polynesia",
    nouvelle_caledonie: "New Caledonia",
    wallis_et_futuna: "Wallis and Futuna",
    la_reunion: "Réunion",
    mayotte: "Mayotte",
    taaf: "French Southern and Antarctic Lands",
  },
};

function isEn(lang) {
  return lang === "en";
}

function wrapLongToken(text) {
  if (text == null || text === "") return "";
  return String(text).replace(/([_/.-])/g, "$1\u200b");
}

function isOverlandLeg(_dossier, mark) {
  const from = String(mark?.from || "");
  const to = String(mark?.to || "");
  return /saint-maur/i.test(from) && /la\s*rochelle/i.test(to);
}

/* ---- small helpers for plain-language sentences ---- */

const MONTHS = {
  fr: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

function num(n, lang, digits = null) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  const s = digits == null ? String(Math.round(v * 100) / 100) : v.toFixed(digits);
  return isEn(lang) ? s : s.replace(".", ",");
}

/** "NNO (329°)" — cardinal + degrees, French letters unless English. */
function heading(deg, lang) {
  const d = Number(deg);
  if (!Number.isFinite(d)) return "";
  const card = getCardinalDirection(d, lang);
  return `${card} (${Math.round(d)}°)`;
}

function monthName(m, lang) {
  const i = Number(m) - 1;
  const table = MONTHS[isEn(lang) ? "en" : "fr"];
  return table[i] || String(m);
}

function longDate(iso, lang) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  const day = d.getUTCDate();
  const month = monthName(d.getUTCMonth() + 1, lang);
  return isEn(lang) ? `${day} ${month} ${d.getUTCFullYear()}` : `${day} ${month} ${d.getUTCFullYear()}`;
}

/** Engine reason codes → words. Unknown codes are kept as they are (honest, not hidden). */
const REASONS = {
  off_grid: ["hors de la grille du modèle", "outside the model grid"],
  no_feature_at_point: ["rien au point", "nothing at this point"],
  no_substrate_class: ["nature du fond non classée ici", "seabed class not mapped here"],
  not_generated: ["pas encore calculé", "not computed yet"],
  no_scene_in_bbox: ["aucune image récente ici", "no recent image here"],
  review_requires_admin: ["réservée à l’administration", "administrators only"],
  no_entity: ["rien à vérifier ici", "nothing to check here"],
  not_in_along_pearl: ["non collecté sur cette perle", "not collected on this pearl"],
  rtofs_not_ingested: ["RTOFS pas encore ingéré", "RTOFS not ingested yet"],
  overpass_unavailable: ["Overpass n'a pas répondu", "Overpass did not answer"],
  null: ["pas de donnée", "no data"],
};

function cleanReason(code) {
  let key = String(code ?? "null");
  key = key.replace(/Traceback \(most recent call last\):[\s\S]*/g, "");
  key = key.replace(/<class ['"][^'"]+['"]>/g, "");
  key = key.replace(/:?\bHTTPStatusError\b/g, "");
  key = key.replace(/:+/g, ":").replace(/^:+|:+$/g, "");
  return key || "unavailable";
}

function why(code, lang) {
  const key = cleanReason(code);
  const table = isEn(lang) ? enDict : frDict;
  if (key === "unavailable") return table.iciReasonUnavailable;
  if (key === "no_data") return table.iciReasonNoData;
  const row = REASONS[key];
  if (row) return row[isEn(lang) ? 1 : 0];
  if (/^openmeteo_unavailable/.test(key)) return isEn(lang) ? "Open-Meteo did not answer" : "Open-Meteo n’a pas répondu";
  if (/^rtofs_unavailable/.test(key)) return isEn(lang) ? "RTOFS did not answer" : "RTOFS n’a pas répondu";
  if (/^outside_us_enc/.test(key)) return isEn(lang) ? "Outside NOAA ENC (US charts) coverage" : "Hors couverture des cartes NOAA (ENC US)";
  if (/overpass_unavailable/.test(key)) return REASONS.overpass_unavailable[isEn(lang) ? 1 : 0];
  return key;
}

/** Libellé lisible d’un code moteur (tests et journal). */
export function formatIciReason(code, lang = "fr") {
  return why(code, lang);
}

function joinList(parts, lang) {
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0];
  const last = parts[parts.length - 1];
  return `${parts.slice(0, -1).join(", ")}${isEn(lang) ? " and " : " et "}${last}`;
}

/** "Name (0,3 nm), Other (1,2 nm) et Last (5 nm)". The sheet link is in the UI, not in the text. */
function listPlaces(items, lang, max = 3, kind = null) {
  const slice = (items || []).slice(0, max);
  const parts = slice.map((x) => {
    const name = placeLabel(kind, x, lang);
    const nm = Number.isFinite(x.nm) ? ` (${num(x.nm, lang)} nm)` : "";
    return `${name}${nm}`;
  });
  return joinList(parts, lang);
}

function formatEta(hours, lang) {
  if (hours == null || !Number.isFinite(hours) || hours <= 0) return null;
  const en = isEn(lang);
  if (hours >= 48) {
    const days = Math.round(hours / 24);
    return en ? `${days} days` : `${days} jours`;
  }
  if (hours < 1) {
    const m = Math.max(1, Math.round(hours * 60));
    return `${m} min`;
  }
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (!m) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}

function watersZee(zee) {
  if (!zee) return false;
  if (zee.ashore || String(zee.name || "").startsWith("À terre")) return false;
  if (!zee.mrgid || zee.name === "Haute mer" || zee.name === "High seas") return false;
  return true;
}

function mentionsFormalities(text) {
  return /formalit/i.test(String(text || ""));
}

/** zee-enter, puis zee-ahead, puis zee-exit — seulement dans une ZEE nommée.
 *  En haute mer, seule la phrase zee-exit peut remplacer la phrase actuelle. */
function zeeFilmHit(dossier, lang) {
  const zee = dossier?.zee;
  if (!zee || zee.ashore || String(zee.name || "").startsWith("À terre")) return null;
  const order = watersZee(zee) ? ["zee-enter", "zee-ahead", "zee-exit"] : ["zee-exit"];
  for (const type of order) {
    const text = pickFilmPhrase({ type }, dossier, lang);
    if (text) return { type, text };
  }
  return null;
}

function poeFilmPhrase(dossier, lang) {
  const poe = (dossier?.poe || []).find((p) => p?.name);
  return pickFilmPhrase({
    type: "poe-ahead",
    name: poe?.name,
    payload: poe ? { poe } : {},
  }, dossier, lang);
}

/** Types déjà dits en tête, pour ne pas recoller la ligne d'événement. */
function filmTypesSpokenInOpening(dossier, lang) {
  const types = [];
  const zee = zeeFilmHit(dossier, lang);
  if (zee) types.push(zee.type);
  if (poeFilmPhrase(dossier, lang)) types.push("poe-ahead");
  return types;
}

function zeeFormalities(zee, lang) {
  const en = isEn(lang);
  if (zee.gold) {
    return en
      ? "Entry formalities go through official ports of entry, listed below."
      : "Les formalités d’entrée passent par des ports officiels, listés ci-dessous.";
  }
  if (zee.territory) {
    return en
      ? "French EEZ; the entry formalities are not complete in our data yet."
      : "ZEE française ; les formalités d’entrée ne sont pas encore complètes dans nos données.";
  }
  return en
    ? "Not a French EEZ: check the local entry formalities."
    : "Ce n’est pas une ZEE française : formalités d’entrée locales à vérifier.";
}

// Territorial sea: a known port this close means the boat is not on the high seas.
export const TERRITORIAL_SEA_NM = 12;

function nearKnownPort(dossier) {
  const nearby = dossier?.nearby || {};
  const rows = [
    ...(Array.isArray(dossier?.poe) ? dossier.poe : []),
    ...["marinas", "capitaineries", "wpi"].flatMap((key) => (Array.isArray(nearby[key]) ? nearby[key] : [])),
  ];
  return rows.some((row) => {
    const nm = Number(row?.nm);
    return row?.nm != null && Number.isFinite(nm) && nm <= TERRITORIAL_SEA_NM;
  });
}

// Not at sea: on the road, in the air, alongside.
const OFF_SEA_VEHICLES = new Set(["land", "plane", "quay"]);

/** The nearest stop within `maxNm`, or null. Same position for the sheet and the status. */
export function nearestStop(lat, lon, marks, maxNm = TERRITORIAL_SEA_NM) {
  const la = Number(lat);
  const lo = Number(lon);
  if (lat == null || lon == null || !Number.isFinite(la) || !Number.isFinite(lo)) return null;
  let best = null;
  let bestD = Infinity;
  for (const m of Array.isArray(marks) ? marks : []) {
    const mLat = Number(m?.lat);
    const mLon = Number(m?.lon);
    if (m?.lat == null || m?.lon == null || !Number.isFinite(mLat) || !Number.isFinite(mLon)) continue;
    const d = haversineNm(la, lo, mLat, mLon);
    if (d < bestD) {
      bestD = d;
      best = m;
    }
  }
  if (!best || !(bestD <= maxNm)) return null;
  return { name: best.name, lat: Number(best.lat), lon: Number(best.lon), nm: bestD };
}

/** Distance (nm) from a position to the nearest stop of the route, or null. */
export function nearestStopNm(lat, lon, marks) {
  const la = Number(lat);
  const lo = Number(lon);
  if (lat == null || lon == null || !Number.isFinite(la) || !Number.isFinite(lo)) return null;
  let best = null;
  for (const m of Array.isArray(marks) ? marks : []) {
    const mLat = Number(m?.lat);
    const mLon = Number(m?.lon);
    if (m?.lat == null || m?.lon == null || !Number.isFinite(mLat) || !Number.isFinite(mLon)) continue;
    const d = haversineNm(la, lo, mLat, mLon);
    if (best == null || d < best) best = d;
  }
  return best;
}

/** Saint-Maur, before the road transfer. Cursor 0 sits on this point. */
const SAINT_MAUR_DEPARTURE = { lat: 46.8075, lon: 1.6358 };
const DEPARTURE_TOWN_NM = 1;

/** The boat is not on the high seas, whatever an EEZ lookup says: not at sea
 * (road, plane, alongside), on the Saint-Maur → La Rochelle road transfer,
 * or within the territorial sea of a stop. `fromStop` / `toStop` cover Tracer,
 * where the cast says "main" and a drawn tip clears the vehicle. */
export function highSeasRuledOut({
  vehicle = null,
  nearStopNm: near = null,
  fromStop = null,
  toStop = null,
} = {}) {
  if (isOverlandLeg(null, { from: fromStop, to: toStop })) return true;
  if (vehicle && OFF_SEA_VEHICLES.has(vehicle)) return true;
  const nm = Number(near);
  return near != null && Number.isFinite(nm) && nm <= TERRITORIAL_SEA_NM;
}

const HIGH_SEAS_SENTENCE = /\bhigh seas\b|\bhaute mer\b/i;

/**
 * Server « here » sentences without a « high seas » one the boat's own
 * situation contradicts: ashore or inside an EEZ (same answer), not at sea,
 * or near a stop. The server's wording is kept for everything else.
 */
export function hereWithoutFalseHighSeas(here, { ruledOut = false } = {}) {
  const sentences = Array.isArray(here?.sentences) ? here.sentences : null;
  if (!sentences?.length) return here;
  const zee = here?.zee && typeof here.zee === "object" ? here.zee : {};
  const zeeName = String(zee.name || "");
  const contradicted = ruledOut || zee.ashore || zee.mrgid != null
    || /^(À terre|Ashore)\b/i.test(zeeName);
  if (!contradicted) return here;
  const kept = sentences.filter((s) => !HIGH_SEAS_SENTENCE.test(String(s || "")));
  return kept.length === sentences.length ? here : { ...here, sentences: kept };
}

function ashoreName(zee) {
  const name = String(zee?.name || "");
  if (zee?.ashore || name.startsWith("À terre")) return { ashore: true, extra: name.startsWith("À terre") ? name.slice("À terre".length).trim() : "" };
  if (/^Ashore\b/i.test(name)) return { ashore: true, extra: name.replace(/^Ashore/i, "").trim() };
  return { ashore: false, extra: "" };
}

/** Cursor at 0: still in Saint-Maur, the road transfer to La Rochelle has not started. */
function roadDepartureSentence(dossier, lang) {
  const mark = (dossier?.marks || []).find((m) => m.kind === "leg");
  if (!isOverlandLeg(dossier, mark)) return "";
  const la = Number(dossier?.at?.lat);
  const lo = Number(dossier?.at?.lon);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return "";
  if (haversineNm(la, lo, SAINT_MAUR_DEPARTURE.lat, SAINT_MAUR_DEPARTURE.lon) > DEPARTURE_TOWN_NM) return "";
  return (isEn(lang) ? enDict : frDict).iciDepartureRoadTransfer;
}

/** « High seas » only when an EEZ lookup answered « none », away from any
 * known port. Missing or failed EEZ data never reads as high seas.
 * The Saint-Maur road transfer is not the high seas, even when Tracer leaves
 * the vehicle as "main" and does not set `highSeasRuledOut`. */
export function highSeasClaimAllowed(dossier) {
  if (dossier?.highSeasRuledOut) return false;
  const leg = (dossier?.marks || []).find((m) => m.kind === "leg");
  if (isOverlandLeg(dossier, leg)) return false;
  const zee = dossier?.zee;
  if (!zee || typeof zee !== "object" || zee.unknown) return false;
  if (zee.mrgid || ashoreName(zee).ashore) return false;
  const src = dossier?.sources?.zee;
  if (src === "error" || src === "unavailable") return false;
  return !nearKnownPort(dossier);
}

function zeeSentence(dossier, lang) {
  const en = isEn(lang);
  const departure = roadDepartureSentence(dossier, lang);
  if (departure) return departure;
  const zee = dossier?.zee;
  const highSeas = highSeasClaimAllowed(dossier)
    ? (en
      ? "The boat is on the high seas: no exclusive economic zone, no entry formalities to plan."
      : "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir.")
    : "";
  if (!zee || zee.unknown) return "";
  const ashore = ashoreName(zee);
  if (ashore.ashore) {
    const extra = ashore.extra;
    return en
      ? `The boat is ashore${extra ? ` ${extra}` : ""}, outside any EEZ.`
      : `Le bateau est à terre${extra ? ` ${extra}` : ""}, hors de toute ZEE.`;
  }
  const film = zeeFilmHit(dossier, lang);
  if (!watersZee(zee)) return film?.text || highSeas;
  const spoken = spokenZeeName(zee, lang);
  const territory = TERRITORY[en ? "en" : "fr"][zee.territory];
  const zeeLabel = localizePlaceName(zee.name, lang);
  const where = spoken || (territory ? `${zeeLabel} (${territory})` : zeeLabel);
  const formalities = zeeFormalities(zee, lang);
  if (film?.text) {
    if (mentionsFormalities(film.text)) return film.text;
    return `${film.text} ${formalities}`;
  }
  return en
    ? `The boat is sailing in ${where}. ${formalities}`
    : `Le bateau navigue dans ${where}. ${formalities}`;
}

function stopKey(name) {
  return String(name || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/œ/g, "oe")
    .toLowerCase()
    .replace(/\([^)]*\)/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function sameStopName(a, b) {
  const ka = stopKey(a);
  const kb = stopKey(b);
  if (!ka || !kb) return false;
  return ka === kb || ka.startsWith(`${kb} `) || kb.startsWith(`${ka} `);
}

/** Port header only for a stop of the step the Log is showing. */
function stopOnLogStep(stop, logLeg) {
  if (!stop) return null;
  const from = logLeg?.from || logLeg?.fromStop || "";
  const to = logLeg?.to || logLeg?.toStop || "";
  if (!from && !to) return stop;
  if (sameStopName(stop.name, from) || sameStopName(stop.name, to)) return stop;
  return null;
}

function withoutHighSeasSentences(text) {
  return String(text || "")
    .split(/(?<=[.!?])\s+/)
    .filter((sentence) => sentence && !HIGH_SEAS_SENTENCE.test(sentence))
    .join(" ")
    .trim();
}

/**
 * EEZ sentence for this film step only. An answer tagged for another
 * bucket (the boat was in Adelaide, the step is now Nouméa) is unknown —
 * never spoken here. An untagged answer is the caller's own lookup.
 */
function zeeAtReplay(zee, lat, lon) {
  if (!zee || typeof zee !== "object") return null;
  if (typeof zee.bucket === "string" && zee.bucket) {
    return filmZeeForBucket(zee, filmZeeBucket(lat, lon));
  }
  return zee;
}

/**
 * Here sheet for the boat at the replayed position.
 * Header (port of call) and status (high seas / EEZ) come from that one
 * position. Within TERRITORIAL_SEA_NM of a stop: never « high seas ».
 * The header names that stop only when it is an end of the Log step
 * (a leftover Port-de-Paix sheet does not stay on Marigot → Cayenne).
 * Farther from every stop: no port-of-call sheet. The leg is the step
 * the Log is showing, not a leftover live leg.
 */
export function replayHereFrame({
  lat,
  lon,
  marks,
  zee = null,
  logLeg = null,
  lang = "fr",
  nearNm = TERRITORIAL_SEA_NM,
} = {}) {
  const alongside = nearestStop(lat, lon, marks, nearNm);
  const onStep = stopOnLogStep(alongside, logLeg);
  const named = zeeAtReplay(zee, lat, lon);
  const from = logLeg?.from || logLeg?.fromStop || "";
  const to = logLeg?.to || logLeg?.toStop || "";
  // The Log step and the position go on the dossier, so the Saint-Maur road
  // transfer reads as in Tracer: departure sentence at J0, never high seas.
  const dossier = {
    zee: named,
    highSeasRuledOut: Boolean(alongside),
    sources: !named || named.unknown ? { zee: "unavailable" } : { zee: "vliz-local" },
    poe: [],
    nearby: {},
    at: { lat: Number(lat), lon: Number(lon) },
    marks: from || to ? [{ kind: "leg", from, to }] : [],
  };
  const highSeas = highSeasClaimAllowed(dossier);
  let statusText = zeeSentence(dossier, lang);
  if (alongside) statusText = withoutHighSeasSentences(statusText);
  // Header and « high seas » cannot both be true: same position, one claim.
  const header = !highSeas && onStep ? onStep : null;
  return {
    stop: header ? { name: header.name, lat: header.lat, lon: header.lon } : null,
    highSeas: header ? false : highSeas,
    zee: named,
    statusText,
    leg: from || to ? { from, to } : null,
    at: { lat: Number(lat), lon: Number(lon) },
  };
}

function poeSentence(dossier, lang) {
  const en = isEn(lang);
  const film = poeFilmPhrase(dossier, lang);
  if (film) return film;
  const poe = dossier?.poe || [];
  if (!poe.length) {
    if (!dossier?.zee?.mrgid) return "";
    return en
      ? "No official port of entry is known for this EEZ."
      : "Aucun port d’entrée officiel n’est connu pour cette ZEE.";
  }
  const listed = listPlaces(poe, lang, 4, "poe");
  return en
    ? `Nearest official ports of entry: ${listed}.`
    : `Ports d’entrée officiels les plus proches : ${listed}.`;
}

function ampTrafficTag(item, lang) {
  const kind = item?.traffic || trafficKind(item?.entry, item?.speed);
  if (kind === "forbidden") return isEn(lang) ? "no transit" : "circulation interdite";
  if (kind === "regulated") return isEn(lang) ? "regulated transit" : "circulation régulée";
  return "";
}

function ampSentence(dossier, lang) {
  const items = (dossier?.amp || []).filter((x) => x && x.name);
  if (!items.length) return "";
  const en = isEn(lang);
  const inside = items.find((x) => x.inside === true);
  if (inside) {
    const name = placeLabel("amp", inside, lang);
    const tag = ampTrafficTag(inside, lang);
    const extra = tag ? ` (${tag})` : "";
    return en
      ? `In the marine protected area ${name}${extra}.`
      : `Dans l'aire marine protégée ${name}${extra}.`;
  }
  const nearest = items[0];
  const name = placeLabel("amp", nearest, lang);
  const nm = Number.isFinite(Number(nearest.nm)) ? Number(nearest.nm) : null;
  if (nm == null) {
    const listed = listPlaces(items, lang, 3, "amp");
    return en
      ? `Marine protected areas nearby: ${listed}.`
      : `Aires marines protégées à proximité : ${listed}.`;
  }
  const dist = num(nm, lang);
  return en
    ? `${dist} miles from ${name}.`
    : `À ${dist} milles de ${name}.`;
}

function projectsSentence(dossier, lang) {
  const listed = listPlaces(dossier?.projects, lang, 3, "project");
  if (!listed) return "";
  return isEn(lang)
    ? `Projects and initiatives nearby: ${listed}.`
    : `Projets et initiatives à proximité : ${listed}.`;
}

function harboursSentence(dossier, lang) {
  const en = isEn(lang);
  const bits = [];
  const marinas = listPlaces(dossier?.nearby?.marinas, lang, 3, "marina");
  if (marinas) bits.push(en ? `marinas ${marinas}` : `marinas ${marinas}`);
  const capit = listPlaces(dossier?.nearby?.capitaineries, lang, 2, "capitainerie");
  if (capit) bits.push(en ? `harbour offices ${capit}` : `capitaineries ${capit}`);
  const wpi = listPlaces(dossier?.nearby?.wpi, lang, 2, "wpi");
  if (wpi) bits.push(en ? `commercial ports (WPI) ${wpi}` : `ports de commerce (WPI) ${wpi}`);
  if (!bits.length) return "";
  return en
    ? `Harbours nearby: ${bits.join("; ")}.`
    : `Ports à proximité : ${bits.join(" ; ")}.`;
}

function scienceSentence(dossier, lang) {
  const science = listPlaces(dossier?.science?.nearby, lang, 3, "science");
  if (!science) return "";
  return isEn(lang)
    ? `Scientific datasets around the boat: ${science}.`
    : `Données scientifiques disponibles autour du bateau : ${science}.`;
}

function aroundSentence(dossier, lang) {
  const en = isEn(lang);
  const bits = [
    ampSentence(dossier, lang),
    projectsSentence(dossier, lang),
    harboursSentence(dossier, lang),
    scienceSentence(dossier, lang),
    anchorageSentence(dossier, lang),
    atonSentence(dossier, lang),
  ].filter(Boolean);
  if (bits.length) return bits.join("\n\n");
  return en
    ? "Nothing notable within 30 nautical miles."
    : "Rien de notable à moins de 30 milles.";
}

function anchorageSentence(dossier, lang) {
  const listed = listPlaces(dossier?.nearby?.anchorages, lang, 3, "anchorage");
  if (!listed) return "";
  return isEn(lang)
    ? `Anchorages: ${listed}.`
    : `Mouillages : ${listed}.`;
}

function atonSentence(dossier, lang) {
  const en = isEn(lang);
  const aton = dossier?.aton;
  const listed = listPlaces(aton?.nearby, lang, 3, "aton");
  if (listed) {
    const osm = /osm/i.test(String(aton?.source || "")) ? " (OpenStreetMap)" : "";
    return en ? `Aids to navigation${osm}: ${listed}.` : `Balisage${osm} : ${listed}.`;
  }
  // A thin pearl never looked: say nothing rather than "not collected on this pearl".
  if (aton?.reason && aton.reason !== "not_in_along_pearl") {
    return en
      ? `No aid to navigation recorded here (${why(aton.reason, lang)}).`
      : `Pas de balisage recensé ici (${why(aton.reason, lang)}).`;
  }
  return "";
}

const DERIVED_WORDS = {
  coastline: ["trait de côte", "coastline"],
  sdb: ["bathymétrie satellite", "satellite bathymetry"],
  intertidal: ["zone intertidale", "intertidal zone"],
};

/** "S2B_MSIL2A_20260914T105619_N0512_R094_T31TDM_…" → { sat: "S2B", tile: "T31TDM", date: "2026-09-14" }. */
function parseSentinelId(id) {
  const m = /^(S2[AB])_MSIL(1C|2A)_(\d{4})(\d{2})(\d{2})T\d{6}_N\d+_R\d+_(T\w+?)_/.exec(String(id || ""));
  if (!m) return null;
  return { sat: m[1], level: m[2], date: `${m[3]}-${m[4]}-${m[5]}`, tile: m[6] };
}

export function satelliteSentence(dossier, lang) {
  const en = isEn(lang);
  const s = dossier?.satellites;
  if (!s) return "";
  const scene = s.scene || (s.scenes && s.scenes[0]);
  const derived = s.derived || {};
  const missing = Object.entries(derived)
    .filter(([, v]) => v && v.value == null);
  if (scene) {
    const parsed = parseSentinelId(scene.id);
    const when = longDate(scene.datetime || parsed?.date, lang);
    const product = /sentinel-2/i.test(scene.product || "") || parsed ? "Sentinel-2" : (scene.product || "Sentinel");
    const detail = parsed ? ` (${parsed.sat}${parsed.tile ? `, ${en ? "tile" : "tuile"} ${parsed.tile}` : ""})` : "";
    let tail = "";
    if (missing.length) {
      const names = missing.map(([k]) => (DERIVED_WORDS[k] ? DERIVED_WORDS[k][en ? 1 : 0] : k));
      const reasons = new Set(missing.map(([, v]) => v.reason || "null"));
      let reason = reasons.size === 1 ? why([...reasons][0], lang) : (en ? "not available" : "indisponibles");
      if (!en && names.length > 1 && reason === "pas encore calculé") reason = "pas encore calculés";
      const list = joinList(names, lang);
      const sentence = list[0].toUpperCase() + list.slice(1);
      tail = en ? ` ${sentence}: ${reason}.` : ` ${sentence} : ${reason}.`;
    }
    return en
      ? `Latest satellite image (CDSE): ${product}${detail}${when ? ` on ${when}` : ""} (observation).${tail}`
      : `Dernière image satellite (CDSE) : ${product}${detail}${when ? ` du ${when}` : ""} (observation).${tail}`;
  }
  return en
    ? `No recent satellite image here (${why(s.reason, lang)}).`
    : `Aucune image satellite récente ici (${why(s.reason, lang)}).`;
}

function weatherSentence(dossier, lang) {
  const en = isEn(lang);
  const w = dossier?.weather;
  if (!w) return "";
  const wind = w.wind;
  const wave = w.wave;
  if (!wind && !wave) {
    if (w.status === "pending") {
      return en ? "Weather forecast: loading…" : "Prévision météo : chargement…";
    }
    return en
      ? `Weather forecast unavailable (${why(w.reason, lang)}).`
      : `Prévision météo indisponible (${why(w.reason, lang)}).`;
  }
  const bits = [];
  if (wind?.speedKnots != null) {
    const from = heading(wind.dirFromDeg, lang);
    bits.push(en
      ? `wind ${num(wind.speedKnots, lang)} kn${from ? ` from ${from}` : ""}`
      : `vent ${num(wind.speedKnots, lang)} kn${from ? ` de ${from}` : ""}`);
  }
  if (wave?.hs != null) {
    let sea = en ? `sea ${num(wave.hs, lang)} m` : `mer ${num(wave.hs, lang)} m`;
    if (wave.dirDeg != null) sea += en ? ` from ${heading(wave.dirDeg, lang)}` : ` de ${heading(wave.dirDeg, lang)}`;
    if (wave.periodS != null) sea += en ? `, period ${num(wave.periodS, lang)} s` : `, période ${num(wave.periodS, lang)} s`;
    bits.push(sea);
  }
  if (w.current && w.current.speedKnots != null) {
    const to = heading(w.current.dirToDeg, lang);
    bits.push(en
      ? `current ${num(w.current.speedKnots, lang)} kn${to ? ` toward ${to}` : ""} (NOAA/RTOFS)`
      : `courant ${num(w.current.speedKnots, lang)} kn${to ? ` vers ${to}` : ""} (NOAA/RTOFS)`);
  } else if (w.current == null && w.current_reason) {
    bits.push(en
      ? `current: ${why(w.current_reason, lang)}`
      : `courant : ${why(w.current_reason, lang)}`);
  }
  const model = w.model || w.source || "Open-Meteo";
  return en
    ? `Weather forecast (${model}): ${bits.join(", ")}.`
    : `Prévision météo (${model}) : ${bits.join(", ")}.`;
}

function emodnetSentence(dossier, lang) {
  const en = isEn(lang);
  const e = dossier?.emodnet;
  if (!e) return "";
  const bits = [];
  const depth = e.bathy?.depth_m;
  if (depth != null) bits.push(en ? `${num(depth, lang)} m on the chart` : `${num(depth, lang)} m sur la carte`);
  else if (e.bathy?.reason) bits.push(en ? `depth: ${why(e.bathy.reason, lang)}` : `profondeur : ${why(e.bathy.reason, lang)}`);
  if (e.seabed?.label) bits.push(en ? `seabed ${e.seabed.label}` : `nature du fond : ${e.seabed.label}`);
  else if (e.seabed?.reason === "no_substrate_class") bits.push(why(e.seabed.reason, lang));
  else if (e.seabed?.reason) bits.push(en ? `seabed: ${why(e.seabed.reason, lang)}` : `nature du fond : ${why(e.seabed.reason, lang)}`);
  if (e.cables?.nearby === true) bits.push(en ? "a submarine cable passes here" : "un câble sous-marin passe ici");
  else if (e.cables?.nearby === false || e.cables?.reason) {
    bits.push(en ? "no submarine cable at this point" : "aucun câble sous-marin au point");
  }
  if (!bits.length) {
    return en
      ? `Seabed (EMODnet): ${why(e.reason, lang)}.`
      : `Fond (EMODnet) : ${why(e.reason, lang)}.`;
  }
  return en
    ? `Seabed (EMODnet, observation): ${bits.join("; ")}.`
    : `Fond (EMODnet, observation) : ${bits.join(" ; ")}.`;
}

function reviewSentence(dossier, lang) {
  const en = isEn(lang);
  const r = dossier?.review;
  if (!r) return "";
  const bits = [];
  if (r.zee && r.zee.gold_on != null) {
    bits.push(en
      ? `EEZ formalities ${r.zee.gold_on ? "verified" : "not verified"}`
      : `formalités ZEE ${r.zee.gold_on ? "vérifiées" : "non vérifiées"}`);
  }
  if (r.amp && r.amp.gold_on != null) {
    bits.push(en
      ? `MPA rules ${r.amp.gold_on ? "verified" : "not verified"}`
      : `règles AMP ${r.amp.gold_on ? "vérifiées" : "non vérifiées"}`);
  }
  if (!bits.length) {
    // No sheet to tell: nothing to check here, or the sheet is an internal
    // (admin) status of Blue Intelligence — the visitor is not the one
    // missing a key, so the briefing stays silent about it.
    if (!r.reason || r.reason === "no_entity" || r.reason === "review_requires_admin") return "";
    return en
      ? `Verification sheet: ${why(r.reason, lang)}.`
      : `Fiche de vérification : ${why(r.reason, lang)}.`;
  }
  return en
    ? `Verification sheet: ${bits.join(", ")}.`
    : `Fiche de vérification : ${bits.join(", ")}.`;
}

function signedDelta(n, unit) {
  if (!Number.isFinite(n)) return "";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n} ${unit}`;
}

/**
 * Sentences about the machinery never reach the visitor (mirror of
 * story_cascade.tidy_story). Word boundaries that know accents: `\b` in
 * JavaScript stops at "é".
 */
const W = "(?<![\\p{L}\\d])";
const E = "(?![\\p{L}\\d])";
const STORY_META_RE = new RegExp([
  `${W}jug[eé]e?s?${E}`, `${W}juge${E}`, `${W}class[ée]e?s?${E}`, "classif", `${W}identifiant`, `${W}identifier${E}`, `${W}ID${E}`,
  "s[ée]v[ée]rit", `${W}severity${E}`, `${W}playhead${E}`, `${W}DOI${E}`, "aucune (?:information|donn[ée]e)",
  "no (?:additional|further|extra) (?:information|data|details?)", `${W}event type${E}`, "type d[’']?[ée]v[ée]nement",
  `${W}LOA${E}`, "tirant d[’']eau", `${W}draft${E}`, "briefing nautique", "skipper\\.used", "r[èe]gles? de croisi[èe]re", "cruise rules",
  `${W}watch${E}`, `${W}imm[ée]diate${E}`, "d[ée]cision a [ée]t[ée] prise", "the decision was taken",
].join("|"), "iu");

/** Keep the fact, drop the machinery; "" when nothing is left. Max two sentences. */
export function cleanStoryText(text) {
  const lines = String(text || "")
    .split("\n")
    .map((ln) => ln.replace(/[*_#>`]+/g, "").replace(/^\s*(?:[-•]|\d+[.)])\s+/, "").trim())
    .filter((ln) => ln && !(ln.length < 80 && !/[.!?…]$/.test(ln.replace(/:$/, ""))));
  const raw = lines.join(" ").replace(/\s{2,}/g, " ").trim();
  if (!raw) return "";
  const kept = raw.split(/(?<=[.!?…])\s+(?=\S)/).filter((s) => s.trim() && !STORY_META_RE.test(s));
  return kept.slice(0, 2).join(" ").trim();
}

function eventWaters(ev, lang) {
  const p = ev.payload || {};
  const zee = p.zee || {};
  const raw = ev.name || zee.name;
  const mrgid = Number.isInteger(zee.mrgid) ? zee.mrgid : (Number.isInteger(ev.mrgid) ? ev.mrgid : null);
  return watersLabel(raw, lang, { mrgid, territory: zee.territory || null }) || raw;
}

function eventOrigin(ev) {
  const p = ev.payload || {};
  const raw = ev.name || p.amp?.name || p.harbour?.name || p.poe?.name;
  return originName(raw) || raw;
}

/** Film-script sentence attached to the GET /ici bag. */
export function pickFilmPhrase(ev, bag, lang = "fr") {
  if (typeof ev?.filmPhrase === "string" && ev.filmPhrase.trim()) return ev.filmPhrase.trim();
  const phrases = bag?.filmPhrases;
  if (!phrases || !ev?.type) return "";
  const loc = isEn(lang) ? "en" : "fr";
  const take = (row) => {
    if (!row) return "";
    if (typeof row === "string") return row.trim();
    return String(row[loc] || row.fr || "").trim();
  };
  const type = ev.type;
  if (type === "zee-enter" || type === "zee-exit" || type === "zee-ahead") {
    return take(phrases[type]);
  }
  if (type === "amp-enter" || type === "amp-ahead") {
    const id = ev.payload?.amp?.site_id
      || ev.payload?.amp?.id
      || ev.payload?.amp?.wdpaid
      || ev.payload?.amp?.name
      || ev.name;
    return take(phrases[`${type}:${id}`]) || take(phrases[type]);
  }
  if (type === "poe-ahead") {
    const name = ev.payload?.poe?.name || ev.name;
    return take(phrases[`poe-ahead:${name}`]) || take(phrases["poe-ahead"]);
  }
  return take(phrases[type]);
}

export function phraseForEvent(ev, lang = "fr", { written = false } = {}) {
  if (!ev) return "";
  if (written && ev.story?.status === "ready" && ev.story.text) {
    const tidy = cleanStoryText(ev.story.text);
    if (tidy) return tidy;
  }
  const film = typeof ev.filmPhrase === "string" ? ev.filmPhrase.trim() : "";
  if (film) return film;
  if (typeof ev.phrase === "string" && ev.phrase.trim()) return ev.phrase;
  const en = isEn(lang);
  const p = ev.payload || {};
  const name = eventOrigin(ev);
  switch (ev.type) {
    case "zee-enter": {
      const waters = eventWaters(ev, lang) || (en ? "this EEZ" : "cette ZEE");
      return en
        ? `We have just entered ${waters}.`
        : `On vient d’entrer dans ${waters}.`;
    }
    case "zee-exit":
      return en
        ? "The boat is back on the high seas — no EEZ to clear."
        : "Retour en haute mer — plus de ZEE à déclarer.";
    case "zee-ahead": {
      const when = p.whenNm ?? ev.whenNm;
      const waters = eventWaters(ev, lang) || (en ? "another EEZ" : "une autre ZEE");
      return en
        ? `Ahead${Number.isFinite(when) ? ` in ${Math.round(when)} nm` : ""}: ${waters}.`
        : `Devant${Number.isFinite(when) ? ` dans ${Math.round(when)} nm` : ""} : ${waters}.`;
    }
    case "amp-ahead": {
      const when = p.whenNm ?? ev.whenNm;
      const visit = p.amp?.visitable || p.visitable;
      const tag = ampTrafficTag(p.amp || p, lang);
      const extra = tag ? ` (${tag})` : (visit ? (en ? " (visit page in the pack)" : " (page visite dans le sac)") : "");
      return en
        ? `MPA on the track${Number.isFinite(when) ? ` in ${Math.round(when)} nm` : ""}: ${name || "MPA"}${extra}.`
        : `AMP sur le trait${Number.isFinite(when) ? ` dans ${Math.round(when)} nm` : ""} : ${name || "AMP"}${extra}.`;
    }
    case "poe-ahead":
      return en
        ? `Official port of entry ahead: ${originName(p.poe?.name) || name || "PoE"}${p.poe?.nm != null ? ` (${p.poe.nm} nm)` : ""}.`
        : `Port d’entrée officiel devant : ${originName(p.poe?.name) || name || "PoE"}${p.poe?.nm != null ? ` (${p.poe.nm} nm)` : ""}.`;
    case "amp-enter": {
      const visit = p.amp?.visitable || p.visitable;
      const inside = p.amp?.inside || p.inside;
      const tag = ampTrafficTag(p.amp || p, lang);
      if (inside && tag) {
        return en
          ? `The boat is crossing ${name || "this MPA"} (${tag}).`
          : `On traverse ${name || "cette AMP"} (${tag}).`;
      }
      const extra = tag ? ` (${tag})` : (visit ? (en ? " (visit page in the pack)" : " (page visite dans le sac)") : "");
      return en
        ? `A marine protected area is now inside 30 nm: ${name || "MPA"}${extra}.`
        : `Une aire marine entre dans les 30 milles : ${name || "AMP"}${extra}.`;
    }
    case "wind-shift": {
      const kind = p.kind || ev.kind || "forecast";
      const src = p.source ? `, ${p.source}` : "";
      const delta = signedDelta(p.dTws, "kn");
      return en
        ? `Wind ${p.tws} kn / ${p.twd}° (kind: ${kind}${src})${delta ? ` — ${delta}` : ""}.`
        : `Vent ${p.tws} kn / ${p.twd}° (kind: ${kind}${src})${delta ? ` — ${delta}` : ""}.`;
    }
    case "wind-gale": {
      const kind = p.kind || ev.kind || "forecast";
      return en
        ? `Gale: ${p.tws} kn (kind: ${kind}${p.galePct != null ? `, gale ${p.galePct}%` : ""}).`
        : `Coup de vent : ${p.tws} kn (kind: ${kind}${p.galePct != null ? `, gale ${p.galePct} %` : ""}).`;
    }
    case "current-shift": {
      const kind = p.kind || ev.kind || "forecast";
      return en
        ? `Current ${p.kn} kn / ${p.dir}° (kind: ${kind}${p.source ? `, ${p.source}` : ""})${p.invert ? " — direction reversed" : ""}.`
        : `Courant ${p.kn} kn / ${p.dir}° (kind: ${kind}${p.source ? `, ${p.source}` : ""})${p.invert ? " — inversion" : ""}.`;
    }
    case "hs-shift": {
      const kind = p.kind || ev.kind || "forecast";
      return en
        ? `Significant wave ${p.hs} m (kind: ${kind}${p.alert ? ", alert" : ""}).`
        : `Houle ${p.hs} m (kind: ${kind}${p.alert ? ", alerte" : ""}).`;
    }
    case "wx-alert": {
      const bits = [];
      if (p.rainMm != null) bits.push(en ? `rain ${p.rainMm} mm/h` : `pluie ${p.rainMm} mm/h`);
      if (p.gale) bits.push(en ? "gale" : "coup de vent");
      if (p.hs != null) bits.push(`Hs ${p.hs} m`);
      const kind = p.kind || "forecast";
      return en
        ? `Weather alert (kind: ${kind}): ${bits.join(" · ") || "threshold"}.`
        : `Alerte météo (kind: ${kind}) : ${bits.join(" · ") || "seuil"}.`;
    }
    case "marina-refuge": {
      const port = p.harbour?.name || name || (en ? "a harbour" : "un port");
      const nm = p.harbour?.nm;
      const rain = p.rainMm != null ? (en ? `Rain ${p.rainMm} mm/h (GFS). ` : `Pluie ${p.rainMm} mm/h (GFS). `) : "";
      return en
        ? `${rain}Refuge: ${port}${nm != null ? ` at ${nm} nm` : ""}.`
        : `${rain}Repli : ${port}${nm != null ? ` à ${nm} nm` : ""}.`;
    }
    case "depth-alert": {
      // Skipper wording: shelf (Coastal / Cruise) or grounding (Ocean). Never "haut-fond" for a 15 m shelf.
      if (p.label && Number.isFinite(p.alertM)) {
        const head = p.label === "talonnage"
          ? (en ? "Grounding risk" : "Risque de talonner")
          : (en ? "Approaching the shelf" : "On approche du plateau");
        return en
          ? `${head}: ${p.depthM} m sounded, under ${p.alertM} m (${p.source || "DTM"}, kind: observation; not for navigation).`
          : `${head} : ${p.depthM} m sondés, sous ${p.alertM} m (${p.source || "DTM"}, kind: observation ; ne convient pas à la navigation).`;
      }
      return en
        ? `Shallow sounding ${p.depthM} m (${p.source || "DTM"}, kind: observation; not for navigation).`
        : `Haut-fond ${p.depthM} m (${p.source || "DTM"}, kind: observation ; ne convient pas à la navigation).`;
    }
    case "group": {
      if (en && ev.digest?.en) return ev.digest.en;
      if (!en && ev.digest?.fr) return ev.digest.fr;
      const members = (p.members || []).join(" + ");
      return en
        ? `Along this leg: ${members}.`
        : `Depuis cette jambe : ${members}.`;
    }
    default:
      return "";
  }
}

function eventSentence(dossier, lang, written = false) {
  const ev = dossier?.event;
  if (!ev) return "";
  return phraseForEvent(ev, lang, { written });
}

function legSentence(dossier, lang) {
  const en = isEn(lang);
  const mark = (dossier?.marks || []).find((m) => m.kind === "leg");
  const polar = dossier?.polar || {};
  const to = mark?.to ? displayStopName(mark.to, lang) : mark?.to;
  const from = mark?.from ? displayStopName(mark.from, lang) : mark?.from;
  if (mark?.vehicle === "plane" || mark?.phase === "air-out" || mark?.phase === "air-return") {
    const quay = from || "";
    return en
      ? `The boat stays at the dock${quay ? ` in ${quay}` : ""} during the air hop.`
      : `Le bateau reste à quai${quay ? ` à ${quay}` : ""} pendant le transfert aérien.`;
  }
  const overland = isOverlandLeg(dossier, mark);
  const speed = !overland && Number.isFinite(polar.speedKnots) ? polar.speedKnots : null;
  const eta = formatEta(polar.etaHours, lang);
  const bits = [];
  if (to && (speed != null || eta || overland)) {
    if (overland) {
      bits.push(en
        ? `Overland leg${from ? ` from ${from}` : ""} to ${to}${eta ? `: still ${eta} on the road` : ""} (the boat is not at sea yet).`
        : `Étape terrestre${from ? ` de ${from}` : ""} vers ${to}${eta ? ` : encore ${eta} de route` : ""} (le bateau n’est pas encore en mer).`);
    } else {
      bits.push(en
        ? `Heading for ${to}${from ? ` from ${from}` : ""}${eta ? `: still ${eta} at sea` : ""}${speed != null ? ` at ${num(speed, lang)} knots` : ""}.`
        : `Cap sur ${to}${from ? ` depuis ${from}` : ""}${eta ? ` : encore ${eta} de mer` : ""}${speed != null ? ` à ${num(speed, lang)} nœuds` : ""}.`);
    }
  } else if (speed != null) {
    bits.push(en ? `Boat speed on this leg: ${num(speed, lang)} knots.` : `Vitesse sur cette jambe : ${num(speed, lang)} nœuds.`);
  }
  // « Polaire » une fois — déjà sur polar-box (« Polaires chargées »).
  // Le nom du bateau reste sous Polaires / Paramètres avancés, pas ici.
  return bits.join(" ");
}

function depthSentence(dossier, lang) {
  const d = Number(dossier?.depthOffshore);
  if (!Number.isFinite(d) || Math.abs(d) < 1) return "";
  const m = Math.round(Math.abs(d));
  return isEn(lang)
    ? `Offshore depth about ${m} m (GEBCO Compilation Group; indicative, not for navigation).`
    : `Profondeur au large : environ ${m} m (GEBCO Compilation Group ; indicatif, ne convient pas à la navigation).`;
}

export function climatologySentence(dossier, lang) {
  const en = isEn(lang);
  const c = dossier?.climatology;
  if (!c) return "";
  const month = c.month;
  const point = c.point || c;
  const w = point.wind_atlas?.most_likely || point.wind_atlas?.vector_mean;
  const wave = point.wave;
  const cur = point.current;
  const zone = c.wind;
  const src = c.source;
  if (src === "unavailable" && !w && !zone) {
    return en
      ? "The climatology atlas did not answer; the clock keeps the typical wind of the zone."
      : "L’atlas de climatologie n’a pas répondu ; l’horloge garde le vent typique de la zone.";
  }
  const bits = [];
  if (w) {
    bits.push(en
      ? `typical wind ${num(w.speed_knots, lang)} kn from ${heading(w.dir_deg, lang)}`
      : `vent typique ${num(w.speed_knots, lang)} kn de ${heading(w.dir_deg, lang)}`);
  } else if (zone) {
    bits.push(en
      ? `typical wind of the zone ${num(zone.speedKnots, lang)} kn from ${heading(zone.dirFromDeg, lang)}`
      : `vent typique de la zone ${num(zone.speedKnots, lang)} kn de ${heading(zone.dirFromDeg, lang)}`);
  }
  if (wave?.hs_p50_m != null || wave?.hs_p90_m != null) {
    const parts = [];
    if (wave.hs_p50_m != null) parts.push(en ? `${num(wave.hs_p50_m, lang)} m on average` : `${num(wave.hs_p50_m, lang)} m en moyenne`);
    if (wave.hs_p90_m != null) parts.push(en ? `${num(wave.hs_p90_m, lang)} m on rough days (P90)` : `${num(wave.hs_p90_m, lang)} m les jours agités (P90)`);
    let sea = (en ? "sea " : "mer ") + parts.join(", ");
    if (wave.period_s != null) sea += en ? `, period ${num(wave.period_s, lang)} s` : `, période ${num(wave.period_s, lang)} s`;
    if (wave.dir_deg != null) sea += en ? `, from ${heading(wave.dir_deg, lang)}` : `, de ${heading(wave.dir_deg, lang)}`;
    bits.push(sea);
  }
  if (cur && cur.speed_knots != null) {
    const to = cur.direction_to_deg != null ? heading(cur.direction_to_deg, lang) : "";
    bits.push(en
      ? `current ${num(cur.speed_knots, lang)} kn${to ? ` toward ${to}` : ""}`
      : `courant ${num(cur.speed_knots, lang)} kn${to ? ` vers ${to}` : ""}`);
  }
  const rose = c.rose || point.wind_atlas;
  if (rose?.calm_pct != null) bits.push(en ? `calm ${num(rose.calm_pct, lang)}% of the time` : `calme ${num(rose.calm_pct, lang)} % du temps`);
  if (rose?.gale_pct != null) bits.push(en ? `gale ${num(rose.gale_pct, lang)}% of the time` : `coup de vent ${num(rose.gale_pct, lang)} % du temps`);
  if (rose?.stat === "rose" && Array.isArray(rose.directions_from) && rose.directions_from.length) {
    bits.push(en ? "wind rose available" : "rose des vents disponible");
  }
  const nearbyCyc = c.cyclone?.nearby ?? point.cyclone?.nearby;
  const crossings = c.crossings?.count ?? point.cyclone?.crossings_if_leg?.count;
  if (nearbyCyc != null || crossings != null) {
    const cyc = [];
    if (nearbyCyc != null) {
      cyc.push(nearbyCyc
        ? (en ? `${nearbyCyc} passed nearby` : `${nearbyCyc} passé${nearbyCyc > 1 ? "s" : ""} à proximité`)
        : (en ? "none nearby" : "aucun à proximité"));
    }
    if (crossings != null) {
      cyc.push(crossings
        ? (en ? `${crossings} track${crossings > 1 ? "s" : ""} cross this leg` : `${crossings} trajectoire${crossings > 1 ? "s" : ""} croise${crossings > 1 ? "nt" : ""} cette jambe`)
        : (en ? "none crosses this leg" : "aucune trajectoire ne croise cette jambe"));
    }
    bits.push((en ? "historical cyclones (IBTrACS): " : "cyclones historiques (IBTrACS) : ") + cyc.join(", "));
  }
  const period = c.period || point.period;
  const doi = c.doi?.wind || point.doi?.wind;
  const provenance = c.provenance?.wind || point.provenance?.wind;
  const when = monthName(month, lang);
  const head = src === "atlas"
    ? (en ? `Climatology for ${when} (Copernicus Marine atlas` : `Climatologie de ${when} (atlas Copernicus Marine`)
    : (en ? `Climatology for ${when} (zone fallback` : `Climatologie de ${when} (repli de zone`);
  const tail = [];
  if (period) tail.push(String(period).replace("-", "–"));
  if (doi) tail.push(`DOI ${doi}`);
  else if (provenance) {
    const product = String(provenance).split("·")[0].trim();
    if (product) tail.push(en ? `source ${product}` : `source ${product}`);
  }
  return `${head}${tail.length ? `, ${tail.join(", ")}` : ""})${bits.length ? ` : ${bits.join(" ; ")}.` : "."}`;
}

function sourceSentence(dossier, lang) {
  const en = isEn(lang);
  const bi = dossier?.sources?.bi;
  const zee = dossier?.sources?.zee;
  const notes = [];
  if (zee === "error" && dossier?.zee?.mrgid) {
    notes.push(en
      ? "Marine Regions/VLIZ did not answer for the EEZ."
      : "Marine Regions/VLIZ n’a pas répondu pour la ZEE.");
  }
  if ((dossier?.poe || []).some((p) => /douane\.gouv\.fr/i.test(String(p.url || "")))) {
    notes.push(en ? "Entry sheets: douane.gouv.fr." : "Fiches d’entrée : douane.gouv.fr.");
  }
  if (bi === "unavailable" && !pearlKind(dossier) && !dossier?.thin) {
    notes.push(en
      ? "Blue Intelligence layers did not answer: only the EEZ and the World Port Index are kept."
      : "Les couches Blue Intelligence n’ont pas répondu : seuls la ZEE et les ports WPI sont conservés.");
  } else if (bi === "partial" && !pearlKind(dossier) && !dossier?.thin) {
    notes.push(en
      ? "Some Blue Intelligence layers are missing: the briefing tells only what arrived."
      : "Certaines couches Blue Intelligence manquent : le briefing ne raconte que ce qui est arrivé.");
  }
  return notes.join(" ");
}

/** "thin" | "rich" for a pearl standing in for the live bag, null for the live bag itself. */
export function pearlKind(dossier) {
  if (!dossier) return null;
  if (dossier.pearl === "rich" || dossier.pearl === "thin") return dossier.pearl;
  return dossier.thin ? "thin" : null;
}

/** Source of `narrateIci` — deterministic rules, never `llm.lastSource`. */
export const ICI_BRIEFING_SOURCE = "rules";

export function narrateIci(dossier, lang = "fr", { written = false } = {}) {
  if (!dossier) return "";
  // A pearl (the along bag standing in while the full bag is on its way)
  // never collected weather, satellite or the sheet — those only make sense
  // now: say nothing about them rather than "not collected on this pearl".
  // A thin pearl also skipped the seabed and the aids to navigation; a rich
  // one carries them and tells them.
  const kind = pearlKind(dossier);
  const live = kind == null;
  const thin = kind === "thin";
  const spokenTypes = new Set(filmTypesSpokenInOpening(dossier, lang));
  const evType = dossier?.event?.type;
  const parts = [
    [zeeSentence(dossier, lang), poeSentence(dossier, lang)].filter(Boolean).join(" "),
    aroundSentence(dossier, lang),
    live ? satelliteSentence(dossier, lang) : "",
    live ? weatherSentence(dossier, lang) : "",
    thin ? "" : emodnetSentence(dossier, lang),
    live ? reviewSentence(dossier, lang) : "",
    evType && spokenTypes.has(evType) ? "" : eventSentence(dossier, lang, written),
    thin ? "" : depthSentence(dossier, lang),
    climatologyShownOnBanner(dossier) ? "" : climatologySentence(dossier, lang),
    legSentence(dossier, lang),
    live ? sourceSentence(dossier, lang) : "",
  ].filter(Boolean);
  const seen = new Set();
  const unique = [];
  for (const p of parts) {
    if (seen.has(p)) continue;
    seen.add(p);
    unique.push(p);
  }
  return unique.join("\n\n");
}

/** Same condition as the NOW climatology card (`infoItemsFromBag`) — one place only. */
export function climatologyShownOnBanner(dossier) {
  const c = dossier?.climatology;
  return Boolean(c && (c.point || c.wind) && c.month != null);
}

/**
 * Same briefing, split around the places it names so the UI can link them
 * (map focus + official sheet / Google Maps). Plain text is unchanged:
 * `segments.map((s) => s.text).join("")` === `narrateIci(dossier, lang)`.
 */
export function narrateIciSegments(dossier, lang = "fr", opts = {}) {
  const text = narrateIci(dossier, lang, opts);
  if (!text) return [];
  return segmentBriefingWithSources(text, briefingEntities(dossier, lang));
}
