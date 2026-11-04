/**
 * Libellés d'escale et de distance (FV2).
 * Le nom stocké ne change pas : seul l'affichage est réécrit.
 */
import en from "../i18n/en.js";
import fr from "../i18n/fr.js";
import { nmToRoundedKm } from "./berryLegs.js";
import { lookup as lookupToponym } from "../engine/toponyms.js";

function isEn(lang) {
  return String(lang || "").toLowerCase().startsWith("en");
}

function fold(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/œ/g, "oe")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Région officielle d'une autre escale : on ne la recolle pas sur un autre lieu. */
const REGION_OWNERS = [
  ["corse", "ajaccio"],
  ["corsica", "ajaccio"],
  ["martinique", "fort-de-france"],
  ["guadeloupe", "pointe-a-pitre"],
  ["saint-barthelemy", "gustavia"],
  ["saint-martin", "marigot"],
  ["saint-pierre-et-miquelon", "saint-pierre"],
  ["guyane", "cayenne"],
  ["french guiana", "cayenne"],
  ["polynesie francaise", "papeete"],
  ["french polynesia", "papeete"],
  ["wallis-et-futuna", "mata-utu"],
  ["wallis and futuna", "mata-utu"],
  ["nouvelle-caledonie", "noumea"],
  ["new caledonia", "noumea"],
  ["mayotte", "dzaoudzi"],
  ["taaf", "tromelin"],
  ["taaf", "europa"],
  ["la reunion", "saint-gilles"],
  ["reunion", "saint-gilles"],
  ["nouvelle-ecosse", "halifax"],
  ["nova scotia", "halifax"],
  ["berry", "saint-maur"],
  ["indre", "saint-maur"],
  ["berry, indre", "saint-maur"],
];

function dictFor(lang) {
  return isEn(lang) ? en : fr;
}

function labelOf(key, lang, t) {
  if (typeof t === "function") {
    const value = t(key);
    if (value && value !== key) return value;
  }
  return dictFor(lang)[key] || key;
}

function isSaintMaur(name) {
  return fold(name).replace(/-/g, " ").startsWith("saint maur");
}

function isAzores(name) {
  const base = fold(name);
  return base === "acores" || base === "azores" || base === "the azores" || base === "les acores";
}

function foreignRegion(base, region) {
  const foldedBase = fold(base);
  const foldedRegion = fold(region);
  const owners = REGION_OWNERS.filter(([known]) => known === foldedRegion);
  if (!owners.length) return false;
  return !owners.some(([, owner]) => foldedBase.includes(owner));
}

/**
 * Nom montré au visiteur.
 * Saint-Maur → « Saint-Maur (Indre) ».
 * « Açores (Corse) » → « Açores » / « Azores (Portugal) ».
 * « Ajaccio (Corse) » reste tel quel.
 */
export function displayStopName(name, lang = "fr", t = null) {
  const raw = String(name || "").replace(/\s+/g, " ").trim();
  if (!raw) return "";
  if (isSaintMaur(raw)) return labelOf("fv2StopSaintMaur", lang, t);
  const match = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(raw);
  let base = raw;
  let region = "";
  if (match) {
    base = match[1].trim();
    region = match[2].trim();
    if (foreignRegion(base, region)) region = "";
  }
  if (isSaintMaur(base)) return labelOf("fv2StopSaintMaur", lang, t);
  if (isAzores(base)) return labelOf("fv2StopAzores", lang, t);
  if (!region) return base;
  if (isEn(lang)) region = englishRegion(region);
  return `${base} (${region})`;
}

/** « Polynésie française » → « French Polynesia » in English; unknown regions stay as written. */
const REGION_EN = Object.freeze({ "nouvelle-écosse": "Nova Scotia" });

function englishRegion(region) {
  const fixed = REGION_EN[String(region).toLowerCase()];
  if (fixed) return fixed;
  const row = lookupToponym(region);
  const en = row && row.kind !== "high_seas" && row.kind !== "overlap" ? String(row.en || "").trim() : "";
  return en || region;
}

/** « Açores (Corse) » → « Açores ». « Ajaccio (Corse) » ne bouge pas. */
export function withoutForeignRegion(name) {
  const raw = String(name || "").replace(/\s+/g, " ").trim();
  const match = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(raw);
  if (!match) return raw;
  if (foreignRegion(match[1], match[2])) return match[1].trim();
  return raw;
}

/** Distance routière : kilomètres, et les heures s'il y en a. Jamais de nm. */
export function landLegDistanceClause(nm, hours, lang = "fr") {
  const km = nmToRoundedKm(nm);
  if (km == null) return "";
  const loc = isEn(lang) ? "en-US" : "fr-FR";
  const kmText = `${km.toLocaleString(loc)} km`;
  const h = Number(hours);
  if (!Number.isFinite(h) || h <= 0) return kmText;
  return `${kmText}, ≈ ${String(h)} h`;
}

/** La phrase routière porte déjà les km : la ligne d'horloge ne répète pas des nm. */
export function filmClockWithoutRoadNm(clockLine) {
  return String(clockLine || "")
    .replace(/^[\d\s\u202f\u00a0.,]+\s*nm\b\s*(?:·\s*)?/i, "")
    .trim();
}

/** Transfert routier en km, avec les tournures déjà verrouillées (by road / par la route). */
export function roadTransferLabel(nm, hours, t, lang = "fr", fromName = "", toName = "", byRoad = "", unitRoadHours = "", unitKm = "km") {
  const km = nmToRoundedKm(nm);
  if (km == null || !Number.isFinite(Number(hours))) return "";
  const loc = isEn(lang) ? "en-US" : "fr-FR";
  const tr = typeof t === "function" ? t : (key) => key;
  return tr("fv2RoadTransfer", {
    from: displayStopName(fromName, lang, tr),
    to: displayStopName(toName, lang, tr),
    km: km.toLocaleString(loc),
    unitKm,
    byRoad,
    hours: String(Number(hours)),
    roadHours: unitRoadHours,
  });
}

/** Distance restante vers le port de destination, dans le panneau gauche. */
export function destinationPortLabel(nm, t, lang = "fr") {
  if (nm == null || !Number.isFinite(Number(nm))) return "—";
  const loc = isEn(lang) ? "en-US" : "fr-FR";
  const tr = typeof t === "function" ? t : (key) => key;
  return tr("fv2NmToPort", {
    nm: Math.round(Number(nm)).toLocaleString(loc),
  });
}
