import type { Channel3CatalogItem } from "../api/types";
import { isPayPalSupportedCurrency } from "./paypalCurrencies";

export function itemPresentmentCurrency(item: Channel3CatalogItem): string {
  return String(item.target_currency || item.price_currency || "EUR")
    .trim()
    .toUpperCase();
}

/** Gate fund CTA on backend capability when shipped, else PayPal currency list. */
export function wishlistItemFundable(item: Channel3CatalogItem): boolean {
  if (typeof item.funding_supported === "boolean") {
    return item.funding_supported;
  }
  return isPayPalSupportedCurrency(itemPresentmentCurrency(item));
}

export type WishlistPledgeInput = {
  amountMajor: string;
  description: string;
  contributor?: string;
  target_id: string;
  lang?: string;
  currency: string;
};

/** Values forwarded to POST /pledges (currency field = contract gap until backend honors it). */
export function wishlistPledgeBody(
  item: Channel3CatalogItem,
  input: Omit<WishlistPledgeInput, "currency" | "target_id"> & { target_id?: string },
): {
  amount_eur: string;
  currency: string;
  description: string;
  milestone_id: string;
  contributor?: string;
  kind: string;
  target_id: string;
  lang?: string;
} {
  const currency = itemPresentmentCurrency(item);
  return {
    amount_eur: input.amountMajor,
    currency,
    description: input.description,
    milestone_id: "",
    contributor: input.contributor,
    kind: "project_pledge",
    target_id: String(input.target_id || item.project_id || "").trim(),
    lang: input.lang,
  };
}
