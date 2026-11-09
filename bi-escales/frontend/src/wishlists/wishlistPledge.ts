import type { Channel3CatalogItem } from "../api/types";

export function itemPresentmentCurrency(item: Channel3CatalogItem): string {
  return String(item.target_currency || item.price_currency || "EUR")
    .trim()
    .toUpperCase();
}

/** API flag from `enrich_item_funding` — sole source of truth for fund CTA. */
export function wishlistItemFundable(item: Channel3CatalogItem): boolean {
  return Boolean(item.paypal_currency_supported);
}

export function wishlistPledgeBody(
  item: Channel3CatalogItem,
  input: { amountMajor: string; description: string; contributor?: string; lang?: string },
): {
  amount_eur: string;
  description: string;
  milestone_id: string;
  contributor?: string;
  kind: string;
  target_id: string;
  lang?: string;
  /** PayPal JS SDK presentment only; not sent in POST /pledges body. */
  currency: string;
} {
  return {
    amount_eur: input.amountMajor,
    description: input.description,
    milestone_id: "",
    contributor: input.contributor,
    kind: "project_pledge",
    target_id: String(item.project_id || "").trim(),
    lang: input.lang,
    currency: itemPresentmentCurrency(item),
  };
}
