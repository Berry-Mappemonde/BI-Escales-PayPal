import type { Channel3CatalogItem } from "../api/types";

/** Prefer wishlist line quantity; catalogue seed quantity only when line quantity is absent. */
export function wishlistLineQuantity(item: Pick<Channel3CatalogItem, "quantity" | "quantity_needed">): number {
  const lineQty = item.quantity;
  if (lineQty != null && Number.isFinite(Number(lineQty))) {
    return Math.max(1, Math.trunc(Number(lineQty)));
  }
  const needed = item.quantity_needed;
  if (needed != null && Number.isFinite(Number(needed))) {
    return Math.max(1, Math.trunc(Number(needed)));
  }
  return 1;
}

/** Unit price fields from API only — never derive from line target ÷ quantity. */
export function unitPriceFields(item: Channel3CatalogItem): Pick<
  Channel3CatalogItem,
  "price_amount_minor" | "price_currency" | "price_display"
> {
  return {
    price_amount_minor: item.unit_price_amount_minor ?? item.price_amount_minor,
    price_currency: item.unit_price_currency ?? item.price_currency,
    price_display: item.unit_price_display ?? item.price_display,
  };
}
