/**
 * Idée n° 3 : reçu « Comment ce film a été fait » sous le film Rédigé.
 * Le serveur range au clic Rédigé des compteurs mesurés pendant la chaîne
 * (official_store.film_receipt). On ne garde que des nombres et des verdicts
 * servis : aucune étape absente n'est inventée, aucun chiffre n'est estimé ici.
 */
import { modelI18nKey, llmSourceI18nKey } from "./llmSourceLabel.js";

const nonNeg = (v) => (Number.isInteger(v) && v >= 0 ? v : null);
const verdict = (v) => (v === "pass" || v === "fail" ? v : null);

export function publicFilmReceipt(data) {
  if (!data?.hasWritten) return null;
  const r = data?.receipt;
  if (!r || typeof r !== "object") return null;
  const models = [];
  for (const row of Array.isArray(r.models) ? r.models : []) {
    const calls = nonNeg(row?.calls);
    if (!calls) continue;
    models.push({
      model: String(row?.model || ""),
      source: String(row?.source || ""),
      tier: String(row?.tier || ""),
      calls,
      cached: nonNeg(row?.cached) || 0,
    });
  }
  const llmCalls = nonNeg(r.llmCalls);
  if (llmCalls === null && !models.length) return null;
  const out = { models, llmCalls: llmCalls ?? 0, cacheHits: nonNeg(r.cacheHits) ?? 0 };
  for (const k of ["ruleFallbacks", "rewritten", "fallen", "faults", "judgeFailed", "ultra_edit", "ultra_judge", "lightning"]) {
    const v = nonNeg(r[k]);
    if (v !== null) out[k] = v;
  }
  for (const k of ["reread", "reread_en"]) {
    const v = verdict(r[k]);
    if (v) out[k] = v;
  }
  if (typeof r.reviewed === "boolean") out.reviewed = r.reviewed;
  if (typeof r.at === "string") out.at = r.at;
  // R45 : pas de webSourceCount serveur. Le compteur Tavily du reçu est celui des
  // sources affichées (publicFilmWebContext, dédoublonnées, 3 au plus).
  return out;
}

/**
 * Libellé i18n d'une ligne de modèle. Token Factory (source nemotron-*) : l'id servi
 * tranche (Super VL, Ultra, Lightning). Un repli (NIM, OpenRouter, Claude) garde son
 * propre libellé : il ne reçoit jamais « Token Factory ».
 */
export function receiptModelKey(row) {
  const source = String(row?.source || "").toLowerCase();
  if (source.startsWith("nemotron-")) {
    return modelI18nKey(row?.model) || llmSourceI18nKey(row?.source, "", row?.model);
  }
  return llmSourceI18nKey(row?.source, "", row?.model);
}

/** Lignes de modèle regroupées par libellé, dans l'ordre du nombre d'appels. */
export function receiptModelRows(receipt) {
  const byKey = new Map();
  for (const row of receipt?.models || []) {
    const key = receiptModelKey(row);
    const prev = byKey.get(key) || { key, calls: 0, cached: 0 };
    prev.calls += row.calls;
    prev.cached += row.cached || 0;
    byKey.set(key, prev);
  }
  return [...byKey.values()].sort((a, b) => b.calls - a.calls || a.key.localeCompare(b.key));
}

/**
 * Lignes du reçu, dans l'ordre réel de la chaîne. Une étape sans compteur est omise.
 * Chaque ligne : { key, vars } pour t(key, vars).
 */
export function receiptLines(receipt, webSourceCount = 0) {
  if (!receipt) return [];
  const lines = [];
  if (receipt.llmCalls || receipt.cacheHits) {
    lines.push({ key: "filmReceiptCalls", vars: { n: receipt.llmCalls, cached: receipt.cacheHits } });
  }
  if (Number.isInteger(receipt.rewritten)) {
    lines.push({ key: "filmReceiptRewritten", vars: { n: receipt.rewritten, fallen: receipt.fallen ?? 0 } });
  }
  if (receipt.ruleFallbacks) {
    lines.push({ key: "filmReceiptRuleFallbacks", vars: { n: receipt.ruleFallbacks } });
  }
  if (receipt.ultra_judge) {
    lines.push({
      key: receipt.reviewed ? "filmReceiptJudgedPass" : "filmReceiptJudgedFail",
      vars: { n: receipt.judgeFailed ?? 0 },
    });
  }
  if (receipt.reread) {
    lines.push({ key: receipt.reread === "pass" ? "filmReceiptRereadPass" : "filmReceiptRereadFail", vars: {} });
  }
  if (receipt.reread_en) {
    lines.push({ key: receipt.reread_en === "pass" ? "filmReceiptRereadEnPass" : "filmReceiptRereadEnFail", vars: {} });
  }
  if (Number.isInteger(receipt.faults)) {
    lines.push({ key: "filmReceiptFaults", vars: { n: receipt.faults } });
  }
  if (webSourceCount > 0) {
    lines.push({ key: "filmReceiptTavily", vars: { n: webSourceCount } });
  }
  return lines;
}
