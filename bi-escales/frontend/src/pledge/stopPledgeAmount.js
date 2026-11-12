/**
 * Montant affiché et montant envoyé à POST /pledges pour la fiche d'escale.
 * Les tarifs fixes viennent du catalogue GET /prices (aligné serveur).
 */

/** @typedef {{ prices?: Array<{ kind?: string; amount_eur?: string; free_amount?: boolean }> }} PriceCatalog */

const FALLBACK_EXACT = {
  berth: "30.00",
  night: "60.00",
  meal: "60.00",
  care: "40.00",
  cabin_leg: "80.00",
};

/** @param {string} kind @param {PriceCatalog | null | undefined} catalog */
export function catalogExactPrice(kind, catalog) {
  const key = String(kind || "").trim();
  if (!key) return null;
  const row = (catalog?.prices || []).find((item) => item.kind === key);
  if (row?.free_amount) return null;
  const fromApi = String(row?.amount_eur || "").trim();
  if (fromApi) return fromApi;
  return FALLBACK_EXACT[key] ?? null;
}

/** @param {string} kind @param {PriceCatalog | null | undefined} catalog */
export function defaultAmountForKind(kind, catalog) {
  const exact = catalogExactPrice(kind, catalog);
  if (exact) return exact;
  if (kind === "mile" || kind === "common_fund") return "1.00";
  // A gift to a stop: a round starting amount the supporter changes.
  if (kind === "stop_gift") return "10.00";
  return null;
}

/**
 * Unit price to show beside a kind: the fixed catalogue price, 1.00 for a mile,
 * null when the supporter chooses the amount (common fund, project donation).
 * @param {string} kind @param {PriceCatalog | null | undefined} catalog
 */
export function unitPriceForKind(kind, catalog) {
  const key = String(kind || "").trim();
  const row = (catalog?.prices || []).find((item) => item.kind === key);
  if (row?.free_amount) return null;
  return catalogExactPrice(key, catalog) || (key === "mile" ? "1.00" : null);
}

/** Montant réellement envoyé à l'API (tarif fixe prioritaire). */
export function pledgeOrderAmount(kind, userAmount, catalog, quantity) {
  if (quantity !== undefined) {
    const unit = catalogExactPrice(kind, catalog) || (kind === "mile" ? "1.00" : null);
    if (unit) return (Math.round(Number(unit) * 100) * quantity / 100).toFixed(2);
  }
  const exact = catalogExactPrice(kind, catalog);
  if (exact) return exact;
  const normalized = String(userAmount ?? "").trim().replace(",", ".");
  // A cleared gift must fail validation rather than silently donating one euro.
  return normalized || (kind === "stop_gift" ? "" : "1.00");
}

export function pledgeAmountReadOnly(kind, catalog) {
  return catalogExactPrice(kind, catalog) !== null;
}

/** @param {{ kind?: string; amount_eur?: string }} suggested @param {PriceCatalog | null | undefined} catalog */
export function amountFromSuggestedPledge(suggested, catalog) {
  const kind = String(suggested?.kind || "mile").trim() || "mile";
  const exact = catalogExactPrice(kind, catalog);
  if (exact) return exact;
  const raw = String(suggested?.amount_eur || "").trim();
  return raw || defaultAmountForKind(kind, catalog) || "1.00";
}

/** Jalon PayPal pour une promesse cabine depuis l'escale courante. */
export function cabinLegMilestoneId(schedule, stopMilestoneId, stopName) {
  const legs = schedule?.legs || [];
  if (!legs.length) return "";
  const byId = legs.find((leg) => {
    const from = String(leg.from_milestone_id || "").trim();
    return from && stopMilestoneId && from === stopMilestoneId;
  });
  if (byId?.id) return byId.id;
  const name = String(stopName || "").trim();
  if (!name) return "";
  const byName = legs.find((leg) => String(leg.from_name || "").trim() === name);
  return byName?.id || "";
}
